# Pesquisa: builds Android dentro do Termux

**Consultado em 18/10/2026.** Este resumo separa demonstrações comunitárias de uma validação do Xbox360Recomp: os relatos abaixo provam que certos pipelines funcionaram nos ambientes dos autores, não que este projeto já funcione em um telefone.

## O que outras pessoas conseguiram

- Há APKs Java pequenos realmente montados no Termux por cadeia manual, sem Gradle: AAPT2, `javac`, DEX (`dx` nos exemplos antigos), empacotamento/alinhamento e assinatura. Exemplos incluem [rocket-pig](https://github.com/rocket-pig/compile-apk-helloworld-in-termux), [azmaveth](https://github.com/azmaveth/termux-android-hello) e a coleção [BuildAPKs](https://sdrausty.github.io/docsBuildAPKs/). Eles demonstram aplicações básicas, não equivalência com Gradle/AndroidX/Compose nem builds C++ grandes.
- Há uma demonstração mais próxima deste caso no projeto [termux-ndk, issue #165](https://github.com/lzhiyong/termux-ndk/issues/165): o autor relata `hello-jni` e um exemplo C++/JNI GL3 compilados no aparelho, com repacotamento e assinatura. A tentativa precisou desabilitar cross-compilation, substituir AAPT2 x86_64 e usar `c++_shared`; a mesma discussão menciona falhas de CMake/STL e dependências em tempo de execução. É um proof-of-concept específico, não uma receita universal.
- O repositório [termux-ndk](https://github.com/Lzhiyong/termux-ndk) adapta ferramentas para Android ARM64, com escopo declarado de aarch64/Android 9+. A existência desse port confirma que o host do NDK precisa ser adaptado; não significa que os executáveis Linux x86_64 do NDK oficial funcionem diretamente no Termux.
- A documentação oficial do [NDK para outros sistemas de build](https://developer.android.com/ndk/guides/other_build_systems) separa compilador host, target triple e sysroot. A receita [ndk-sysroot do Termux](https://github.com/termux/termux-packages/blob/master/packages/ndk-sysroot/build.sh) reaproveita headers/runtime para o target Android; Clang/CMake/Ninja usados no build precisam ser executáveis host compatíveis com Termux.
- Projetos maiores expõem limites que não aparecem em Hello World. A tentativa documentada para [llama.cpp](https://github.com/ggml-org/llama.cpp/discussions/8737), por exemplo, registra falhas envolvendo `execinfo.h` e CMake. Amostras simples não validam ReXGlue, Vulkan, SDL ou múltiplas bibliotecas nativas.

## Pipeline de APK e implicações

Para um APK com Java e `.so`, a cadeia precisa cobrir: compilação C/C++ para `arm64-v8a`; compilação Java; D8 para DEX; AAPT2 para recursos/manifest; inclusão das bibliotecas em `lib/arm64-v8a/`; `zipalign`; assinatura e verificação com `apksigner`; por fim, instalação pelo Android. D8 é preferível aos exemplos legados com `dx` quando há lambdas Java 8. A documentação oficial pede alinhamento antes de assinar e descreve `zipalign -P 16` para APKs com bibliotecas nativas: [D8](https://developer.android.com/tools/d8), [AAPT2](https://developer.android.com/tools/aapt2), [zipalign](https://developer.android.com/tools/zipalign) e [apksigner](https://developer.android.com/tools/apksigner).

AAPT2 e zipalign precisam ser compatíveis com o host Termux; binários Linux x86_64 do Android SDK não são substitutos. O JAR do D8 e o JAR do apksigner podem ser executados por um JDK compatível, mas os caminhos/versões ainda precisam ser verificados no aparelho. O empacotamento do APK e a compilação da biblioteca são etapas distintas: um `.so` compilado não prova que o APK instala, carrega ou roda.

## O que root não resolve

Root não instala ferramentas, headers, sysroot ou JDK e não converte executáveis Linux x86_64 em executáveis Android ARM64. Também não remove automaticamente SELinux, as restrições de execução de arquivos em diretórios privados graváveis, incompatibilidade ABI/loader, dependências de bibliotecas Termux ou falhas de Vulkan/GPU. Fontes primárias: [sandbox Android](https://source.android.com/docs/security/app-sandbox), [conceitos SELinux](https://source.android.com/docs/security/features/selinux/concepts), [mudanças do Android 10](https://developer.android.com/about/versions/10/behavior-changes-10) e [riscos de carregamento dinâmico](https://developer.android.com/privacy-and-security/risks/dynamic-code-loading). O fluxo do builder, portanto, deve rodar no Termux como usuário normal e deixar a instalação para o Package Installer Android.

## Aplicação ao Xbox360Recomp Android

O repositório usa um fork ReXGlue Android fixado, gera código para um XEX e compila um runtime Vulkan/SDL por título em `arm64-v8a`/API 33; o empacotador desktop usa D8, AAPT2, zipalign, apksigner e `libc++_shared.so`. O bridge JNI on-device gera fontes, mas não compila nem empacota o jogo. Módulos/DLLs guest continuam fora do escopo atual. Consulte [docs/ANDROID.md](../docs/ANDROID.md) e [README do builder](README.md).

Conclusão técnica: é plausível montar um fluxo Termux incremental usando Clang/LLD/CMake/Ninja nativos do Termux, sysroot NDK, biblioteca C++ compartilhada, um manifest portátil e ferramentas APK compatíveis. Ainda é necessário validar a build completa e o APK em um Termux real; relatos públicos de apps simples ou de outros projetos não contam como validação deste projeto.
