# SmaliX Desktop

[![Windows](https://img.shields.io/badge/platform-Windows-blue.svg)](#)
[![Python](https://img.shields.io/badge/python-3.10+-blue.svg)](#)
[![License](https://img.shields.io/badge/license-N/A-lightgrey.svg)](#license)

SmaliX Desktop is a Windows desktop application for decompiling Android APKs, editing Smali files, viewing decompiled Java code, rebuilding APKs, aligning and signing APKs, and using an AI assistant for project analysis.

The application is built with Python, Tkinter, CustomTkinter, apktool, and optionally JADX.

> **Authorization notice:** Only analyze applications you own or applications for which you have explicit permission. Reverse engineering and APK modification may be restricted by local law and application terms.

---

## Features

- Decompile APK files with apktool
- Open existing apktool output folders
- Use fast code-only decompilation or full resource decompilation
- Browse and edit Smali classes
- View Java output from JADX
- Use a built-in Smali-to-Java outline when JADX is unavailable
- Highlight Java and Smali syntax
- Explain Smali instructions and directives
- Search an entire decompiled project
- Find callers and callees for a method
- Display a method-level call graph
- Synchronize Java lines with matching Smali lines
- Apply quick patches:
  - return `true`
  - return `false`
  - return `null`
  - return `void`
  - invert a conditional branch
  - replace an instruction with `nop`
- Rebuild APK files
- Align rebuilt APK files with `zipalign`
- Sign APK files with `apksigner`
- Create or reuse a debug signing keystore
- Chat with Claude, Gemini, or OpenAI
- Require approval before AI-generated edits and build actions

---

## Requirements

### Required for source execution

| Requirement | Purpose |
|---|---|
| Windows 10 or Windows 11 | Primary supported platform |
| Python 3.10 or newer | Runs the desktop application |
| JDK 17 or newer | Provides `java` and `keytool` |
| apktool | Decompiles and rebuilds APK files |
| Android SDK Build Tools | Provides `zipalign` and `apksigner` |
| CustomTkinter | Provides the modern desktop UI |

### Optional

| Requirement | Purpose |
|---|---|
| JADX | Displays real decompiled Java source |
| `keyring` | Stores API keys in the operating system credential store |
| AI provider API key | Enables the built-in AI assistant |

### Verified development environment

The project was compiled successfully in the following environment:

- Python `3.14.7`
- CustomTkinter `6.0.0`
- Microsoft JDK 17
- JADX available through the system PATH
- apktool, zipalign, and apksigner require configuration in the Tools dialog before use

Python 3.11 or 3.12 is recommended for better third-party compatibility.

---

## Installation

Choose one of these methods:

- **Run from source:** use Python and the project files.
- **Run the built application:** use `dist\main.exe` without installing Python.

### Option A: Run from source

#### 1. Clone the repository

```powershell
git clone https://github.com/MahialamDev/smailx.git
cd smailx
```

#### 2. Create a virtual environment

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

If PowerShell blocks virtual-environment activation:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
```

#### 3. Install the optional keyring package

The keyring package stores API keys in Windows Credential Manager:

```powershell
pip install keyring
```

Without `keyring`, API keys are stored in the fallback JSON file described below.

#### 4. Configure external tools

Open the application and use **Tools** to configure:

- JDK `java`
- JDK `keytool`
- apktool executable or JAR
- Android SDK `zipalign`
- Android SDK `apksigner`
- optional JADX executable

#### 5. Start the application

```powershell
python main.py
```

### Option B: Run the already-built executable

1. Open the project folder.
2. Open the `dist` folder.
3. Double-click `main.exe`.

The executable starts with no Python command:

```text
dist\main.exe
```

The executable still requires JDK, apktool, Android SDK Build Tools, and any selected optional tools. Configure their paths from **Tools** after the app opens.

---

## External Tools

Open **Tools** in the application to configure executable paths.

### JDK

The JDK must provide `java` and `keytool`.

```powershell
java -version
keytool -help
```

Example environment configuration:

```powershell
setx JAVA_HOME "C:\Program Files\Microsoft\jdk-17.0.20.8-hotspot"
setx PATH "%JAVA_HOME%\bin;%PATH%"
```

### apktool

SmaliX supports:

- an apktool executable in `PATH`
- an apktool executable selected in **Tools**
- an apktool JAR selected in **Tools**
- an `apktool*.jar` file found in the application directory or current working directory

Apktool JAR files are executed with the configured JDK:

```powershell
java -jar apktool.jar d -f -o output input.apk
```

### Android SDK Build Tools

Install Android SDK Build Tools, then configure `ANDROID_HOME` or `ANDROID_SDK_ROOT`.

Typical executable locations:

```text
<ANDROID_SDK>\build-tools\<latest-version>\zipalign.exe
<ANDROID_SDK>\build-tools\<latest-version>\apksigner.bat
```

Example:

```powershell
setx ANDROID_HOME "C:\Users\<username>\AppData\Local\Android\Sdk"
setx ANDROID_SDK_ROOT "C:\Users\<username>\AppData\Local\Android\Sdk"
```

### JADX

JADX is optional. If it is not available in `PATH`, open **Tools** and use **Download JADX**.

The downloader:

1. retrieves the latest JADX release metadata from GitHub
2. downloads the JADX ZIP archive
3. extracts it to `%USERPROFILE%\.smalix_desktop\jadx\current`
4. saves the executable path to the application configuration

An existing JADX executable can also be selected manually.

---

## Running a Project

### Open an APK

1. Click **Open APK**.
2. Select an `.apk` file.
3. Enable or disable **Fast (code-only)**.
4. Wait for apktool to finish decompiling and scanning the project.

Fast mode skips resource and manifest decoding. Normal mode provides better resource and manifest support but may take longer.

The apktool project is stored by default under:

```text
%USERPROFILE%\.smalix_desktop\projects\<apk-name>\
```

### Open a Decompiled Folder

1. Click **Open Folder**.
2. Select an apktool output folder containing `smali/` or `smali_classes*`.
3. The folder must normally also contain `apktool.yml`.

An already decompiled project can be opened without repeating the apktool decode step.

---

## Editing Smali

1. Select a `.smali` file in the project tree.
2. Edit the right-hand Smali editor.
3. Press `Ctrl+S` or click **Save**.

Unsaved changes are protected when switching files or closing the application.

Supported editor actions include:

- `Ctrl+F` to search the active editor
- line selection
- syntax highlighting
- clickable line explanations
- method detection
- calls/called-by view
- quick return patches
- conditional inversion
- instruction replacement

The editor has a 5 MB file-size limit.

---

## Java and Smali Synchronization

When JADX output is available, SmaliX:

1. finds the Java source corresponding to the current Smali class
2. displays it in the Java pane
3. maps a clicked Java line to the most likely Smali line
4. highlights and centers the matching Smali block

Without JADX, the Java pane shows a generated Smali outline.

Use the **Sync** checkbox in the toolbar to enable or disable Java-to-Smali synchronization.

---

## Project Search

The search box searches text in project files with the following extensions:

- `.smali`
- `.xml`
- `.yml`
- `.json`
- `.txt`

Search results are capped to keep the interface responsive.

The AI assistant also exposes bounded project search and file-reading actions.

---

## Quick Patches

Place the cursor inside a method in the Smali editor, then use the patch buttons.

### Return patches

The patch assistant replaces the method body with a valid return sequence based on the method return type.

| Patch | Required return type |
|---|---|
| `true` | boolean or integer-like type |
| `false` | boolean or integer-like type |
| `null` | object or array |
| `void` | `void` |

Abstract and native methods cannot be patched.

### Branch flip

Place the cursor on an `if-*` instruction. SmaliX changes it to the inverse conditional.

Examples:

```text
if-eqz -> if-nez
if-ltz  -> if-gez
if-ne   -> if-eq
```

### Replace with NOP

Place the cursor on an instruction and replace it with `nop`.

For invoke instructions, the application warns that a following `move-result` instruction may become invalid.

---

## Rebuild and Sign an APK

### Rebuild

1. Save Smali edits.
2. Click **Rebuild**.
3. Wait for apktool to finish.

The rebuilt APK is normally stored at:

```text
<project>\dist\<apk-name>-smalix-rebuilt.apk
```

If apktool reports framework or resource incompatibilities:

1. open **Tools**
2. select **Fix framework**
3. reopen the APK in normal, not fast, mode

### Sign

**Sign** requires an already rebuilt APK.

The signing workflow:

1. runs `zipalign`
2. creates or reuses a debug keystore
3. signs the aligned APK with `apksigner`
4. verifies ZIP alignment
5. verifies the APK certificate
6. calculates and prints a SHA-256 checksum

The signed output is stored at:

```text
<project>\dist\<apk-name>-smalix-aligned-debugSigned.apk
```

Enable **Random key** to generate a temporary signing keystore.

---

## AI Assistant

Open the right sidebar with the **Chat** button.

### Supported providers

| Provider | Default model |
|---|---|
| Anthropic Claude | `claude-sonnet-5-5` |
| Google Gemini | `gemini-2.5-flash` |
| OpenAI ChatGPT | `gpt-4o` |

Open **Settings** to select a provider, model, API key, and maximum agent step count.

Environment-variable fallback:

```powershell
$env:ANTHROPIC_API_KEY="..."
$env:GEMINI_API_KEY="..."
$env:OPENAI_API_KEY="..."
```

### AI action approval

Read-only actions include:

- `list_dir`
- `read_file`
- `search`
- `open_file`

Project-changing actions require approval:

- `replace_in_file`
- `write_file`
- `patch_return`
- `rebuild`
- `sign`
- `rebuild_sign`

Additional protections:

- file paths must remain inside the project root
- AI writes are limited to 2 MB per file
- the AI cannot directly write build or dist directories
- file contents and search results are length-limited
- edit, patch, rebuild, and sign actions run through preview cards

---

## Configuration and Data

SmaliX stores application data in:

```text
%USERPROFILE%\.smalix_desktop\
```

### Important files

```text
config.json
ai_settings.json
ai_keys.json
projects\
smalix_debug.keystore
jadx\
```

| Path | Purpose |
|---|---|
| `config.json` | Saves external tool paths |
| `ai_settings.json` | Saves provider, model, step limit, and last project folder |
| `ai_keys.json` | Fallback API-key storage when OS keyring is unavailable |
| `projects\` | Decompiled APK projects |
| `smalix_debug.keystore` | Persistent debug signing keystore |
| `jadx\` | Downloaded or extracted JADX installation |

API keys should not be committed to Git or shared in backups.

---

## Project Structure

```text
smailx/
├── main.py             # Application entry point and UI controller
├── config.py           # Constants, tool discovery, settings, and key storage
├── backend_worker.py   # apktool, JADX, rebuild, sign, and subprocess work
├── ai_client.py        # Claude, Gemini, and OpenAI HTTP clients
├── ai_panel.py         # AI chat sidebar and settings interface
├── ai_actions.py       # AI action parsing and safe project executor
├── smali_utils.py      # Smali parsing, highlighting, and explanations
├── sync_mapper.py      # Java-to-Smali line mapping
├── ui_components.py    # Editors, toolbar, tabs, tree, and dialogs
├── requirements.txt    # Python runtime dependencies
├── main.spec           # PyInstaller specification
└── README.md
```

---

## Build a Standalone Windows Executable

The following commands build the Windows executable with the existing `main.spec` configuration.

### 1. Open PowerShell in the project folder

```powershell
cd "C:\Users\<username>\Desktop\Compailer"
```

Replace the path with the actual location of the repository.

### 2. Activate the virtual environment

```powershell
.\.venv\Scripts\Activate.ps1
python --version
```

If the virtual environment is not created yet:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

### 3. Install PyInstaller

```powershell
python -m pip install pyinstaller
```

Verify the installation:

```powershell
python -m PyInstaller --version
```

### 4. Build using the existing specification

```powershell
python -m PyInstaller main.spec --noconfirm
```

This command:

- reads the build settings from `main.spec`
- bundles Python and application dependencies
- creates a windowed application without a console
- uses the project name `main`
- writes temporary build files to `build\`
- writes the executable to `dist\`

### 5. Locate and run the executable

After a successful build:

```powershell
Get-Item ".\dist\main.exe"
.\dist\main.exe
```

Verified output location:

```text
dist\main.exe
```

Verified executable size:

```text
14.36 MB
```

### 6. Clean rebuild

To remove previous build output before rebuilding:

```powershell
Remove-Item -Recurse -Force .\build -ErrorAction SilentlyContinue
Remove-Item -Recurse -Force .\dist -ErrorAction SilentlyContinue
python -m PyInstaller main.spec --noconfirm
```

Do not delete `main.spec`; it contains the executable build configuration.

### Alternative direct build command

To build without using `main.spec`:

```powershell
python -m PyInstaller --noconsole --onefile --name SmaliX main.py
```

The direct build creates:

```text
dist\SmaliX.exe
```

The existing `main.spec` build is recommended because it matches the current project configuration.

### What is and is not bundled

The executable includes Python and the application modules. It does not include or replace external Android tooling.

Users still need to install or configure:

- JDK
- `keytool`
- apktool
- Android SDK `zipalign`
- Android SDK `apksigner`
- optional JADX

---

## Troubleshooting

### `customtkinter` is missing

```powershell
python -m pip install --upgrade customtkinter
python -c "import customtkinter; print(customtkinter.__version__)"
```

### apktool is not found

- configure apktool in the **Tools** dialog
- add apktool to `PATH`
- place an `apktool*.jar` in the application or project directory
- verify that `java` is available if using an apktool JAR

### zipalign or apksigner is not found

- install Android SDK Build Tools
- set `ANDROID_HOME` or `ANDROID_SDK_ROOT`
- configure the executables manually in **Tools**

### Framework or rebuild errors

- use **Fix framework** in **Tools**
- reopen the APK in normal mode
- verify that the Android SDK platform JAR is available

### JADX does not show Java code

- install or download JADX
- verify the original APK exists next to the decompiled project
- use normal APK decompilation instead of fast mode
- open a valid JADX `sources` directory

### AI API errors

- verify the API key
- verify the selected provider and model
- verify network and proxy access
- retry after HTTP `429` or provider `529` responses
- verify whether `keyring` is available

---

## Development Validation

There is currently no dedicated automated test suite or CI workflow.

Run the available syntax validation with:

```powershell
python -m compileall -q .
python main.py
```

Perform a manual smoke test after code changes:

- open an APK
- open a decompiled folder
- edit and save a Smali file
- synchronize Java and Smali lines
- run project search
- find callers
- rebuild the APK
- align and sign the APK
- test AI read actions
- test AI edit approval and rejection

---

## Privacy and Security

- project files remain on local disk
- APK decompilation occurs locally
- API requests are sent directly to the selected AI provider
- project context may be included in AI requests
- API keys are stored in an OS keyring, fallback JSON file, or environment variable
- AI cannot write outside the project root
- AI cannot write build or dist directories directly
- AI edits, patches, builds, and signing require approval

Do not place API keys or signing keystores in the source repository.

---

## Contributing

1. Fork the repository.
2. Create a feature branch.
3. Compile Python source after changes.
4. Run manual tests for affected external-tool workflows.
5. Open a pull request or issue.

Useful contributions include:

- automated tests
- GitHub Actions Windows builds
- Linux and macOS validation
- screenshots and demo GIFs
- improved Smali validation
- stronger Java-to-Smali mapping
- additional patch templates
- release packaging
- license information

---

## License

This repository does not currently include a license file or license declaration.

Do not distribute the project commercially or assume reuse rights until the repository owner has added an explicit license.

Third-party tools and libraries retain their own licenses:

- apktool
- JADX
- Android SDK Build Tools
- CustomTkinter
- keyring
