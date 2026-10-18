# Build Android pelo Termux — estado experimental

## O que já funciona no protótipo

O launcher consegue gerar fontes C++ ReXGlue para um XEX único. Após a geração, o novo botão **Export generated sources (ZIP)** salva o projeto pelo seletor de documentos do Android. O arquivo contém fontes e manifest, mas não inclui os arquivos originais do jogo. Alguns caminhos do manifest apontam para o armazenamento privado do launcher. Por isso, o ZIP ainda não é um projeto pronto para compilar no Termux.

Este diretório é documentação do caminho de porte; **não há ainda um `build.sh` Termux funcional nem um APK de jogo gerado no telefone**.

## O root ajuda?

O root pode facilitar operações administrativas, mas não fornece Clang, CMake, Ninja, sysroot nem ferramentas de empacotamento. Também não transforma os executáveis Linux x86-64 do NDK em programas executáveis no Android ARM64. A documentação do NDK lista toolchains de host para Linux x86-64, macOS x86-64 e Windows x86-64.

Não execute o compilador, o XEX ou código C++ gerado com `su`. O jogo e os artefatos são entradas não confiáveis; compilar como root exporia o aparelho a riscos desnecessários. O Termux pode compilar como o próprio usuário, e a instalação normal do APK assinado deve ser confirmada pelo instalador Android. O Android 10/API 29+ removeu a permissão de execução do diretório privado gravável do app, então não se deve extrair o compilador em `filesDir` e tentar iniciá-lo por `ProcessBuilder`.

## O que falta para um build Termux completo

1. Exportar o ZIP para uma pasta que o usuário também consiga abrir no Termux, por exemplo Downloads, e extrair uma cópia no `$HOME` do Termux. A permissão de armazenamento compartilhado do Termux é configurada pelo próprio Termux.
2. Tornar o manifest portátil: substituir caminhos absolutos do app, permitir apontar para os dados do jogo selecionados pelo usuário e manter os arquivos do jogo fora do ZIP por padrão.
3. Gerar um `CMakeLists.txt` de título compatível com o runtime Android deste fork. O caminho desktop que faz essa preparação está em `android_build.py`, mas também invoca um gerador host Linux/Windows que não é executável diretamente no Termux.
4. Usar o Clang/LLD/CMake/Ninja instalados no Termux com o sysroot do NDK r27c em um toolchain CMake próprio para `arm64-v8a`, API 33 e alinhamento ELF de 16 KiB. Essa combinação ainda precisa ser portada e validada em um telefone real.
5. Empacotar a biblioteca gerada e a classe Java em um APK. Isso exige ferramentas Android compatíveis com Termux para gerar DEX, processar/empacotar recursos, alinhar e assinar. O exemplo comunitário ligado abaixo demonstra APK Java simples em Termux, não o build nativo C++ deste projeto.

## Fluxo proposto quando o builder existir

No launcher: gerar o código e exportar o ZIP pelo seletor Android. No Termux: extrair o ZIP no espaço privado do Termux, configurar os caminhos para os dados do jogo, compilar como usuário normal e gerar um APK assinado. Por fim, abrir o APK no instalador do Android para que o usuário confirme a instalação.

**Root não é requisito desse fluxo e não será usado para executar binários ou código guest.** O primeiro marco entregue é somente a exportação segura das fontes. Não use os comandos do build desktop como se fossem comandos Termux: o host CLI e as ferramentas NDK atuais dependem de um ambiente de build ainda não portado.

## Referências

- [Android NDK: CMake](https://developer.android.com/ndk/guides/cmake)
- [Android NDK: outros sistemas de build e host tags](https://developer.android.com/ndk/guides/other_build_systems)
- [Android 10: execução no diretório privado do app](https://developer.android.com/about/versions/10/behavior-changes-10)
- [Android: riscos de carregamento dinâmico de código](https://developer.android.com/privacy-and-security/risks/dynamic-code-loading)
- [Exemplo comunitário de build APK Java em Termux](https://github.com/azmaveth/termux-android-hello)
