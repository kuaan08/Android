# Build Android no Termux — builder experimental

## Estado real

O launcher consegue gerar C++ para um XEX único e exportar um ZIP pelo seletor Android. O ZIP agora contém `generated-project/` e `xbo-game.json`; o manifest exportado usa referências portáteis (`../game` e `../game/<xex_path>`). **Os arquivos originais do jogo não são incluídos.** O preparador `build_generated.py` valida o hash e o cabeçalho XEX2, rejeita DLLs guest, configura um target Android, tenta compilar `libxbo_game.so` e, por padrão, invoca o empacotador APK do projeto.

Na sandbox Linux ARM64, o fixture sintético original do CI (`li r3,1; blr`) passou pelo codegen: o CLI encontrou uma função e emitiu C++ (`ctx.r3.s64 = 1`). A cross-build compilou `libxbo_game.so` e `librexruntime.so` para AArch64/Android API 33; ambos têm segmentos ELF `PT_LOAD` alinhados a 16 KiB. Esse teste usou Clang 20 da sandbox, o sysroot NDK r27c e um runtime compiler-rt temporário para AArch64 — não o Clang nativo do Termux.

A compilação Java e a etapa D8 também passaram. O empacotamento parou em AAPT2: o Build Tools oficial Linux baixado é x86-64 e não executa nesta sandbox ARM64; `zipalign` e `apksigner` não chegaram a ser testados. **APK assinado e execução em aparelho/Termux continuam sem validação.** O modo `--native-only` permite testar a biblioteca sem empacotar.

## Root

Root não é requisito e o builder não chama `su`. Root não instala o Clang/NDK/sysroot, não fornece AAPT2/D8/zipalign/apksigner e não transforma ferramentas Linux x86-64 em executáveis Android ARM64. Compile como usuário normal e deixe o instalador Android solicitar confirmação para instalar o APK. Não execute o XEX nem código gerado com privilégios de root.

## Preparar os arquivos

1. No launcher, gere o C++ e use **Export generated sources (ZIP)**. Extraia o ZIP em uma pasta privada do Termux, por exemplo `~/xbo360-build/`.
2. Extraia, em separado, os dados do jogo de sua propriedade para `~/xbo360-build/game/`, mantendo o caminho indicado em `xbo-game.json`. O arquivo XEX precisa ter o mesmo SHA-256 registrado no ZIP. O jogo não deve ser colocado dentro do APK pelo builder.
3. Instale no Termux Python 3, Git, CMake 3.25+, Ninja, Clang/LLD e JDK 17 ou 21 (por exemplo, usando os pacotes nativos do Termux). Para empacotar também são necessários `aapt2`, `zipalign`, D8 (`d8.jar`), `apksigner` (`apksigner.jar`) e Android Platform 35 (`android.jar`). Confira `command -v aapt2` e `command -v zipalign`; os executáveis nativos precisam ser builds compatíveis com Android/Termux. Os binários Linux x86-64 do SDK não servem. D8 e apksigner devem ser JARs executáveis pelo JDK instalado.
4. Obtenha o sysroot do NDK r27c e a plataforma Android API 35. `fetch_ndk_sysroot.py` consulta os metadados oficiais do Google, valida o SHA-1 publicado e extrai somente o sysroot do arquivo NDK; ele nunca executa as ferramentas host Linux x86-64. O arquivo compactado é grande e é removido após a extração por padrão. O `android.jar` da plataforma 35 e as ferramentas APK continuam sendo instalações separadas.

```sh
python3 /caminho/para/Android/termux/fetch_ndk_sysroot.py \
  --dest "$HOME/android-ndk-r27c-termux"
```

## Comando

Defina os caminhos das ferramentas. Os nomes reais de pacote podem variar; use `command -v` para os executáveis e aponte os JARs para arquivos que existam:

```sh
export ANDROID_NDK_SYSROOT="$HOME/android-ndk-r27c-termux/sysroot"
export ANDROID_HOME="$HOME/android-sdk"
export XBO_ANDROID_JAR="$ANDROID_HOME/platforms/android-35/android.jar"
export XBO_AAPT2="$(command -v aapt2)"
export XBO_ZIPALIGN="$(command -v zipalign)"
export XBO_D8_JAR="$ANDROID_HOME/build-tools/35.0.0/lib/d8.jar"
export XBO_APKSIGNER_JAR="$ANDROID_HOME/build-tools/35.0.0/lib/apksigner.jar"

python3 /caminho/para/Android/termux/build_generated.py \
  --bundle "$HOME/xbo360-build" \
  --game-root "$HOME/xbo360-build/game" \
  --android-sdk "$ANDROID_HOME" \
  --ndk-sysroot "$ANDROID_NDK_SYSROOT" \
  --jobs 2
```

O primeiro build clona a revisão ReXGlue fixada pelo projeto e inicializa seus submódulos; isso exige rede e espaço livre considerável. A saída é `<project-name>.apk` em `termux-build/package/`, assinado com uma chave de debug local. Para abrir o instalador do Android sem root:

```sh
termux-setup-storage
APK=$(find "$HOME/xbo360-build/termux-build/package" -maxdepth 1 -name '*.apk' -print -quit)
cp "$APK" "$HOME/storage/shared/Download/"
termux-open "$HOME/storage/shared/Download/$(basename "$APK")"
```

Confirme a instalação no Package Installer e permita instalações solicitadas pelo Termux, se o Android pedir. Para testar apenas a compilação nativa, acrescente `--native-only`; isso não produz APK.

## Limitações e segurança

- A implementação suporta um XEX e recusa qualquer `.dll`; integração de módulos guest ainda falta.
- A compilação completa C++ e o empacotamento/instalação precisam ser exercitados em Termux/Android real; o probe de `.so` não valida o ReXGlue completo nem compatibilidade de jogo.
- O ZIP não contém os dados do jogo. O APK verifica o SHA-256 do executável e o launcher precisa importar os dados correspondentes depois da instalação.
- A análise e o codegen não garantem que um jogo comercial seja compatível ou jogável. O código gerado e o XEX são entradas não confiáveis; mantenha o build sem root.
- A geração de um APK local não remove as limitações do runtime, Vulkan/GPU, memória, DLLs ou análise de funções do Xbox 360.

## Referências principais

- [Android NDK: CMake](https://developer.android.com/ndk/guides/cmake)
- [Android NDK: outros sistemas de build e host tags](https://developer.android.com/ndk/guides/other_build_systems)
- [Android 10: execução no diretório privado do app](https://developer.android.com/about/versions/10/behavior-changes-10)
- [Android: riscos de carregamento dinâmico de código](https://developer.android.com/privacy-and-security/risks/dynamic-code-loading)
- [Termux package repository](https://github.com/termux/termux-packages)
- [Example de build APK Java em Termux](https://github.com/azmaveth/termux-android-hello) (não demonstra esta pipeline nativa)
- [Pesquisa de tentativas públicas e recomendações para este builder](RESEARCH.md)
