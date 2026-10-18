# Geração C++ experimental no Android

Este diretório implementa uma primeira etapa de recompilação local: o launcher pode criar um projeto ReXGlue a partir de um XEX já importado e gerar os arquivos C++ no armazenamento privado do app. O botão **“Generate C++ on this device (experimental)”** aparece apenas quando o APK foi empacotado com `libxbo360_codegen_jni.so`. A ponte recusa diretórios com DLLs guest; não compila o C++ gerado, não cria um APK jogável e ainda não foi executada em um telefone/emulador. Portanto, isso não é paridade total com a ferramenta desktop.

`CodegenBridge.java` executa o trabalho em um executor serial e publica o progresso por `Handler`. `codegen_jni.cpp` inicializa o runtime ReXGlue com o `Context` do app, chama `InitProject` e `ProjectRecompiler::Run()` com `force=false`. O patch local da função `ManifestPath` preserva maiúsculas/minúsculas: isso é necessário porque o armazenamento externo Android usa componentes como `/Android/` e o filesystem diferencia caixa. Os caminhos são restritos a arquivos/diretórios já acessíveis ao app; o launcher importa os arquivos pela SAF antes de chamar a JNI.

## Como construir o APK experimental

O caminho foi adicionado a `android_build.export(ondevice_codegen=True)`. O target JNI e o runtime já compilaram e linkaram como ELF Android ARM64 usando o sysroot do NDK r27c e Clang ARM64. Isso ainda não equivale a empacotar um APK nem executá-lo em dispositivo. Para gerar o APK completo, use uma máquina com Android SDK platform 35, Build Tools 35, JDK 17, CMake/Ninja e Android NDK r27c:

```sh
python3 android/build_ondevice_codegen.py \
  --sdk "/caminho/para/Android/Sdk" \
  --ndk "/caminho/para/Android/Sdk/ndk/27.2.12479018" \
  --jobs 4
```

A opção prepara o checkout ReXGlue fixado pelo projeto, injeta um target CMake opcional para `libxbo360_codegen_jni.so`, compila também `librexruntime.so` e empacota essas bibliotecas e `libc++_shared.so`. O APK usa o mesmo empacotador do launcher e inclui `CodegenBridge.java`. A atividade inicializa a bridge no main thread e mostra a ação para cada jogo importado. O patcher é fail-closed/idempotente e corrige os caminhos do manifest para Android/Linux.

## Limitações e próximos passos

O maior bloqueio é compilar os fontes C++ gerados no próprio telefone. O APK ainda não contém um toolchain host Android (Clang/LLD/CMake/Ninja e sysroot); sem ele, esta etapa gera fontes, não um jogo instalável. Também faltam suporte a DLLs guest, exportação/compartilhamento dos fontes gerados, recursos/cancelamento para XEX muito grande e testes reais em vários dispositivos. A sandbox já validou sintaxe Java/C++ e fez uma build cross-target parcial de ReXGlue, mas isso não substitui o build completo do target JNI nem a execução em hardware.
