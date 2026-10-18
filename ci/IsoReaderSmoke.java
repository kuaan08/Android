import org.xbo360.app.IsoReader;

import java.io.IOException;
import java.io.RandomAccessFile;
import java.nio.ByteBuffer;
import java.nio.ByteOrder;
import java.nio.channels.FileChannel;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Arrays;
import java.util.Comparator;

/**
 * Host-JVM checks for the actual Android XDVDFS reader.
 * All ISO and XEX content here is independently authored synthetic data.
 */
public final class IsoReaderSmoke {
    private static final byte[] MAGIC = "MICROSOFT*XBOX*MEDIA".getBytes(StandardCharsets.US_ASCII);
    private static final byte[] XEX = "XEX2 synthetic test".getBytes(StandardCharsets.US_ASCII);
    private static int checks;

    private static Path image(Path root, String name, long partition, String entry) throws IOException {
        Path path = root.resolve(name);
        byte[] filename = entry.getBytes(StandardCharsets.US_ASCII);
        ByteBuffer directory = ByteBuffer.allocate(14 + filename.length).order(ByteOrder.LITTLE_ENDIAN);
        directory.putShort((short) 0).putShort((short) 0);
        directory.putInt(34).putInt(XEX.length).put((byte) 0x20).put((byte) filename.length);
        directory.put(filename);
        byte[] header = new byte[2048];
        System.arraycopy(MAGIC, 0, header, 0, MAGIC.length);
        System.arraycopy(MAGIC, 0, header, 2048 - MAGIC.length, MAGIC.length);
        ByteBuffer.wrap(header).order(ByteOrder.LITTLE_ENDIAN).putInt(20, 33).putInt(24, directory.array().length);
        try (RandomAccessFile file = new RandomAccessFile(path.toFile(), "rw")) {
            file.setLength(partition + 34L * 2048 + XEX.length);
            file.seek(partition + 32L * 2048);
            file.write(header);
            file.seek(partition + 33L * 2048);
            file.write(directory.array());
            file.seek(partition + 34L * 2048);
            file.write(XEX);
        }
        return path;
    }

    private static void extractAndCheck(Path file, Path output) throws IOException {
        Files.createDirectories(output);
        try (FileChannel channel = FileChannel.open(file)) {
            new IsoReader(channel).extract(output.toFile(), message -> {});
        }
        if (!Arrays.equals(XEX, Files.readAllBytes(output.resolve("default.xex")))) {
            throw new AssertionError("Extracted XEX bytes differ from the synthetic input");
        }
        checks++;
    }

    private static void mustReject(Path file, Path output) throws IOException {
        Files.createDirectories(output);
        boolean failed = false;
        try (FileChannel channel = FileChannel.open(file)) {
            new IsoReader(channel).extract(output.toFile(), message -> {});
        } catch (IOException expected) {
            failed = true;
        }
        if (!failed) throw new AssertionError("Malformed ISO unexpectedly accepted: " + file);
        checks++;
    }

    public static void main(String[] args) throws Exception {
        Path root = Files.createTempDirectory("xbo360-iso-java-");
        try {
            extractAndCheck(image(root, "xiso.iso", 0, "default.xex"), root.resolve("xiso-output"));
            extractAndCheck(image(root, "xgd3.iso", 34078720, "default.xex"), root.resolve("xgd3-output"));
            mustReject(image(root, "traversal.iso", 0, "../escape.xex"), root.resolve("reject-traversal"));
            if (Files.exists(root.resolve("escape.xex"))) {
                throw new AssertionError("ISO traversal wrote outside its destination");
            }
            Path truncated = image(root, "truncated.iso", 0, "default.xex");
            try (RandomAccessFile file = new RandomAccessFile(truncated.toFile(), "rw")) {
                file.setLength(file.length() - 3);
            }
            mustReject(truncated, root.resolve("reject-truncation"));
            Path badHeader = image(root, "bad-header.iso", 0, "default.xex");
            try (RandomAccessFile file = new RandomAccessFile(badHeader.toFile(), "rw")) {
                file.seek(32L * 2048);
                file.writeByte(0);
            }
            mustReject(badHeader, root.resolve("reject-header"));
            System.out.println("Android IsoReader: " + checks + " Java fixture checks passed");
        } finally {
            try (java.util.stream.Stream<Path> files = Files.walk(root)) {
                files.sorted(Comparator.reverseOrder()).forEach(path -> {
                    try { Files.deleteIfExists(path); }
                    catch (IOException e) { throw new RuntimeException(e); }
                });
            }
        }
    }
}
