#include <jni.h>

#include <algorithm>
#include <atomic>
#include <cctype>
#include <exception>
#include <filesystem>
#include <map>
#include <mutex>
#include <string>
#include <utility>
#include <vector>

#include <rex/codegen/manifest.h>
#include <rex/codegen/progress_reporter.h>
#include <rex/codegen/project_recompiler.h>
#include <rex/logging.h>
#include <rex/main_android.h>
#include <rexglue/commands/init_command.h>

namespace {

std::mutex g_initialize_mutex;
std::mutex g_codegen_mutex;
std::atomic<bool> g_initialized{false};

jstring ToJavaString(JNIEnv* env, const std::string& value) {
  return env->NewStringUTF(value.c_str());
}

bool ReadJavaString(JNIEnv* env, jstring source, std::string& output) {
  if (source == nullptr)
    return false;
  const char* chars = env->GetStringUTFChars(source, nullptr);
  if (chars == nullptr)
    return false;
  output.assign(chars);
  env->ReleaseStringUTFChars(source, chars);
  return true;
}

class JavaProgressReporter final : public rex::codegen::ProgressReporter {
 public:
  JavaProgressReporter(JNIEnv* env, jobject listener) : env_(env), listener_(listener) {
    if (listener_ != nullptr) {
      jclass type = env_->GetObjectClass(listener_);
      if (type != nullptr) {
        on_progress_ = env_->GetMethodID(type, "onProgress", "(Ljava/lang/String;)V");
        env_->DeleteLocalRef(type);
      }
      if (env_->ExceptionCheck())
        env_->ExceptionClear();
    }
  }

  bool valid() const { return listener_ == nullptr || on_progress_ != nullptr; }

  void moduleStarted(std::string_view name, std::size_t index, std::size_t total) override {
    Send("Módulo " + std::to_string(index + 1) + "/" + std::to_string(total) + ": " +
         std::string(name));
  }

  void phaseChanged(std::string_view name) override { Send("Etapa: " + std::string(name)); }

  void moduleFinished(std::chrono::milliseconds elapsed) override {
    Send("Módulo concluído em " + std::to_string(elapsed.count()) + " ms");
  }

  void projectPhaseStarted(std::string_view name) override {
    Send("Projeto: " + std::string(name));
  }

  void projectPhaseFinished() override { Send("Etapa do projeto concluída"); }

 private:
  void Send(const std::string& message) {
    if (listener_ == nullptr || on_progress_ == nullptr)
      return;
    jstring text = ToJavaString(env_, message);
    if (text == nullptr)
      return;
    env_->CallVoidMethod(listener_, on_progress_, text);
    env_->DeleteLocalRef(text);
    if (env_->ExceptionCheck())
      env_->ExceptionClear();
  }

  JNIEnv* env_;
  jobject listener_;
  jmethodID on_progress_ = nullptr;
};

jstring RunCodegen(JNIEnv* env, const std::string& manifest_path,
                   JavaProgressReporter& reporter) {
  if (!reporter.valid())
    return ToJavaString(env, "O listener não implementa onProgress(String).");

  auto manifest = rex::codegen::ManifestConfig::Load(manifest_path);
  if (!manifest)
    return ToJavaString(env, "Não foi possível carregar o manifest ReXGlue informado.");

  rex::codegen::ProjectRecompiler recompiler(std::move(*manifest));
  rex::codegen::ProjectRecompilerOptions options{
      .targets = {},
      .force = false,
      .enableExceptionHandlers = false,
      .reporter = &reporter,
  };
  auto result = recompiler.Run(options);
  if (!result)
    return ToJavaString(env, result.error().what());
  return nullptr;
}

std::vector<std::filesystem::path> FindManifests(const std::filesystem::path& root) {
  std::vector<std::filesystem::path> found;
  std::error_code ec;
  for (const auto& entry : std::filesystem::directory_iterator(root, ec)) {
    if (ec)
      return {};
    if (entry.is_regular_file() && entry.path().extension() == ".toml" &&
        rex::codegen::ManifestConfig::IsManifest(entry.path())) {
      found.push_back(entry.path());
    }
  }
  return found;
}

bool HasGuestDll(const std::filesystem::path& game_root) {
  std::error_code ec;
  std::filesystem::recursive_directory_iterator it(
      game_root, std::filesystem::directory_options::skip_permission_denied, ec);
  const std::filesystem::recursive_directory_iterator end;
  for (; !ec && it != end; it.increment(ec)) {
    if (it->is_regular_file()) {
      std::string extension = it->path().extension().string();
      std::transform(extension.begin(), extension.end(), extension.begin(),
                     [](unsigned char c) { return static_cast<char>(std::tolower(c)); });
      if (extension == ".dll")
        return true;
    }
  }
  // Treat an unreadable directory tree as unsupported rather than silently
  // producing a single-XEX project with guest modules omitted.
  return ec || it != end;
}

}  // namespace

extern "C" JNIEXPORT jboolean JNICALL
Java_org_xbo360_app_CodegenBridge_nativeInitialize(JNIEnv* env, jclass, jobject context) {
  std::lock_guard<std::mutex> lock(g_initialize_mutex);
  if (g_initialized.load(std::memory_order_acquire))
    return JNI_TRUE;

  JavaVM* vm = nullptr;
  if (env->GetJavaVM(&vm) != JNI_OK || vm == nullptr || context == nullptr)
    return JNI_FALSE;
  if (!rex::InitializeAndroidAppFromMainThread(vm, context))
    return JNI_FALSE;

  rex::InitLoggingEarly();
  std::map<std::string, std::string> category_levels;
  auto config = rex::BuildLogConfig(nullptr, "info", category_levels);
  config.log_to_console = false;
  rex::InitLogging(config);
  rex::RegisterLogLevelCallback();

  g_initialized.store(true, std::memory_order_release);
  return JNI_TRUE;
}

extern "C" JNIEXPORT jstring JNICALL
Java_org_xbo360_app_CodegenBridge_nativeRunCodegen(JNIEnv* env, jclass, jstring manifest_path,
                                                    jobject listener) {
  if (!g_initialized.load(std::memory_order_acquire))
    return ToJavaString(env, "A ponte nativa ainda não foi inicializada no thread principal.");
  try {
    std::string path;
    if (!ReadJavaString(env, manifest_path, path))
      return ToJavaString(env, "O caminho do manifest está vazio ou indisponível.");
    std::lock_guard<std::mutex> lock(g_codegen_mutex);
    JavaProgressReporter reporter(env, listener);
    return RunCodegen(env, path, reporter);
  } catch (const std::exception& e) {
    return ToJavaString(env, e.what());
  } catch (...) {
    return ToJavaString(env, "Erro nativo inesperado durante o codegen.");
  }
}

extern "C" JNIEXPORT jstring JNICALL
Java_org_xbo360_app_CodegenBridge_nativeInitAndCodegen(
    JNIEnv* env, jclass, jstring project_name, jstring xex_path, jstring game_root,
    jstring project_root, jobject listener) {
  if (!g_initialized.load(std::memory_order_acquire))
    return ToJavaString(env, "A ponte nativa ainda não foi inicializada no thread principal.");

  try {
    std::string name, xex, game, project;
    if (!ReadJavaString(env, project_name, name) || !ReadJavaString(env, xex_path, xex) ||
        !ReadJavaString(env, game_root, game) || !ReadJavaString(env, project_root, project)) {
      return ToJavaString(env, "Nome ou caminho de entrada inválido.");
    }
    if (name.empty() || xex.empty() || game.empty() || project.empty())
      return ToJavaString(env, "Nome ou caminho de entrada vazio.");

    std::lock_guard<std::mutex> lock(g_codegen_mutex);
    if (HasGuestDll(game))
      return ToJavaString(env, "Este protótipo suporta apenas XEX único; DLLs guest ainda não são integradas.");

    JavaProgressReporter reporter(env, listener);
    if (!reporter.valid())
      return ToJavaString(env, "O listener não implementa onProgress(String).");

    auto manifests = FindManifests(project);
    if (manifests.empty()) {
      rexglue::cli::InitOptions init_options{
          .project_name = name,
          .xex_path = xex,
          .game_root = game,
          .project_root = project,
          .scan_dlls = false,
          .template_dir = {},
          .force = false,
      };
      rexglue::cli::CliContext context;
      auto initialized = rexglue::cli::InitProject(init_options, context);
      if (!initialized)
        return ToJavaString(env, initialized.error().what());
      manifests = FindManifests(project);
    }
    if (manifests.size() != 1)
      return ToJavaString(env, "O projeto deve conter exatamente um manifest ReXGlue.");
    return RunCodegen(env, manifests.front().string(), reporter);
  } catch (const std::exception& e) {
    return ToJavaString(env, e.what());
  } catch (...) {
    return ToJavaString(env, "Erro nativo inesperado durante init/codegen.");
  }
}
