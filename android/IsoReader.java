package org.xbo360.app;

import java.io.*;
import java.nio.ByteBuffer;
import java.nio.ByteOrder;
import java.nio.channels.FileChannel;
import java.util.*;

/** Original bounded XDVDFS reader. Layout checked against antangelo/xdvdfs. */
public final class IsoReader {
    static final byte[] MAGIC = "MICROSOFT*XBOX*MEDIA".getBytes(java.nio.charset.StandardCharsets.US_ASCII);
    static final long[] BASES = {0L, 405798912L, 265879552L, 34078720L};
    final FileChannel channel;
    final long size, base;
    final long rootSector, rootSize;
    int count;
    final Set<String> names = new HashSet<>(), directories = new HashSet<>();
    public interface Progress { void update(String text) throws IOException; }

    public IsoReader(FileChannel input) throws IOException {
        channel = input; size = channel.size(); long detected = -1, sector = 0, length = 0;
        for (long candidate : BASES) {
            long at = candidate + 32L * 2048;
            if (at + 2048 > size) continue;
            byte[] data = read(at, 2048);
            if (Arrays.equals(Arrays.copyOfRange(data, 0, 20), MAGIC) && Arrays.equals(Arrays.copyOfRange(data, 2028, 2048), MAGIC)) {
                detected = candidate; ByteBuffer h = ByteBuffer.wrap(data).order(ByteOrder.LITTLE_ENDIAN);
                sector = Integer.toUnsignedLong(h.getInt(20)); length = Integer.toUnsignedLong(h.getInt(24)); break;
            }
        }
        if (detected < 0) throw new IOException("No XDVDFS volume found. Choose an XISO or XGD1/2/3 image.");
        base = detected; rootSector = sector; rootSize = length;
    }

    byte[] read(long offset, int count) throws IOException {
        if (offset < 0 || count < 0 || offset > size - count) throw new IOException("ISO entry outside image");
        ByteBuffer buffer = ByteBuffer.allocate(count); long at = offset;
        while (buffer.hasRemaining()) { int n = channel.read(buffer, at); if (n <= 0) throw new EOFException("Truncated ISO"); at += n; }
        return buffer.array();
    }

    public void extract(File root, Progress progress) throws IOException {
        directory(root, rootSector, rootSize, 0, progress);
    }

    void directory(File parent, long sector, long length, int depth, Progress progress) throws IOException {
        if (depth > 64 || length > 64L * 1024 * 1024 || !directories.add(sector + ":" + length)) throw new IOException("Invalid ISO directory tree");
        byte[] bytes = read(base + sector * 2048, (int) length);
        ByteBuffer table = ByteBuffer.wrap(bytes).order(ByteOrder.LITTLE_ENDIAN);
        ArrayDeque<Integer> stack = new ArrayDeque<>(); Set<Integer> seen = new HashSet<>();
        if (length > 0) stack.push(0);
        while (!stack.isEmpty()) {
            int pos = stack.pop();
            if (!seen.add(pos) || pos < 0 || pos + 14 > length) throw new IOException("Invalid directory node");
            int left = Short.toUnsignedInt(table.getShort(pos)), right = Short.toUnsignedInt(table.getShort(pos + 2));
            long start = Integer.toUnsignedLong(table.getInt(pos + 4)), len = Integer.toUnsignedLong(table.getInt(pos + 8));
            int attr = Byte.toUnsignedInt(bytes[pos + 12]), n = Byte.toUnsignedInt(bytes[pos + 13]);
            if (n == 0 || pos + 14 + n > length || ++count > 200000) throw new IOException("Invalid ISO directory entry");
            String name = new String(bytes, pos + 14, n, java.nio.charset.StandardCharsets.US_ASCII);
            if (name.equals(".") || name.equals("..") || name.matches(".*[/\\\\:\\x00-\\x1f].*")) throw new IOException("Unsafe ISO filename");
            File target = new File(parent, name);
            if (!names.add(target.getCanonicalPath().toLowerCase(Locale.ROOT))) throw new IOException("Duplicate ISO filename");
            long offset = base + start * 2048;
            if (offset < 0 || len > size - offset) throw new IOException("File outside ISO");
            progress.update("Extracting " + name);
            if ((attr & 16) != 0) {
                if (!target.mkdirs() && !target.isDirectory()) throw new IOException("Cannot create directory");
                if (len > 0) directory(target, start, len, depth + 1, progress);
            } else {
                if (parent.getUsableSpace() < len + 32L * 1024 * 1024) throw new IOException("Not enough storage");
                try (FileOutputStream out = new FileOutputStream(target)) {
                    byte[] buffer = new byte[1024 * 1024]; long remaining = len, at = offset;
                    while (remaining > 0) {
                        progress.update("Extracting " + name);
                        int want = (int) Math.min(buffer.length, remaining);
                        ByteBuffer b = ByteBuffer.wrap(buffer, 0, want); int got = channel.read(b, at);
                        if (got <= 0) throw new EOFException("Truncated file"); out.write(buffer, 0, got); at += got; remaining -= got;
                    }
                }
            }
            if (right != 0 && right != 65535) stack.push(right * 4);
            if (left != 0 && left != 65535) stack.push(left * 4);
        }
    }
}
