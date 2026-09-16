# Installing a GitHub release

Start at [Latest release](https://github.com/JonathanGrocott/better-blender/releases/latest),
or choose a specific version from [all releases](https://github.com/JonathanGrocott/better-blender/releases).
Expand **Assets** beneath its release notes.

## Which files do I need?

| File | Purpose |
| --- | --- |
| `better_blender_mcp-0.5.1-py3-none-any.whl` | MCP server and CLI; also contains the matching Blender add-on. Recommended installation route. |
| `better_blender_bridge-0.5.1.zip` | Add-on only, for manual installation through Blender. Does not install the MCP server. |
| `SHA256SUMS` | SHA-256 checksums for the wheel and add-on ZIP. |
| GitHub's **Source code** archives | Developer source snapshots; these are not the installable add-on ZIP. |

The examples use **0.5.1**. Substitute the downloaded release's version and your
Blender version as needed. Use server and add-on files from the same release.
Python 3.11+ and Blender 3.4.1+ are required. Blender 3.4.1, 4.2.0 and 5.0.1 are
covered by Linux integration tests; Python and installation tests cover Linux,
macOS and Windows. Blender and the MCP server should run under the same user account.

## 1. Install the MCP server

Download the wheel. In a terminal, change to the folder containing it. Install into
a virtual environment so its dependencies are isolated. Pip also downloads the
required Python dependencies; this is not an offline installer.

### macOS / Linux

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install ./better_blender_mcp-0.5.1-py3-none-any.whl
better-blender-mcp install-addon --blender-version 5.0
```

### Windows PowerShell

These commands use the environment's executables directly, without changing
PowerShell's script execution policy:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install .\better_blender_mcp-0.5.1-py3-none-any.whl
.\.venv\Scripts\better-blender-mcp.exe install-addon --blender-version 5.0
```

Use `4.2` or `3.4.1`, for example, if that is the Blender version you run. Close
Blender before replacing an existing add-on. Installation also creates the shared
per-user token. There is no need to download the separate add-on ZIP when using
`install-addon`.

## 2. Enable the Blender add-on

Open Blender's **Preferences → Add-ons** and enable **Better Blender Bridge**.
Leave **Token override** blank to use the generated credential. In a 3D View,
open the sidebar, choose **Better Blender**, and click **Start Bridge**.

For manual installation instead of `install-addon`, use Blender's add-on ZIP
installation command with **`better_blender_bridge-0.5.1.zip`**, then enable it as
above. Run `better-blender-mcp setup` in the Python environment if installing
manually. The add-on ZIP alone is not sufficient for an MCP client connection.

## 3. Connect your MCP client

```bash
better-blender-mcp print-config --client generic
better-blender-mcp doctor
```

On Windows, prefix these commands with `.\.venv\Scripts\` and use the `.exe`
entrypoint, as in step 1. Copy the generated configuration into your client.
`doctor` should report a connected, compatible bridge after it is running.

Desktop clients may not inherit your activated environment. Set the configuration's
`command` to the **absolute path** of `better-blender-mcp` inside this environment:

- macOS/Linux: `/absolute/path/to/.venv/bin/better-blender-mcp`
- Windows: `C:\absolute\path\to\.venv\Scripts\better-blender-mcp.exe`

Keep the environment in that location, or update the client configuration when
moving it. In JSON, escape Windows backslashes or use forward slashes. See
[client-specific setup](client-setup.md) for configuration formats. Treat the
generated token as a credential; do not commit your personalized config.

## Verify a download

Download `SHA256SUMS` alongside both package files. These distributions are
unsigned; checksum comparison detects corrupted downloads, not publisher identity.

Linux:

```bash
sha256sum -c SHA256SUMS
```

macOS:

```bash
shasum -a 256 -c SHA256SUMS
```

Windows PowerShell:

```powershell
Get-FileHash .\better_blender_mcp-0.5.1-py3-none-any.whl -Algorithm SHA256
Get-FileHash .\better_blender_bridge-0.5.1.zip -Algorithm SHA256
Get-Content .\SHA256SUMS
```

Compare each computed hash with its filename's entry in `SHA256SUMS`. If you only
downloaded one package, compare just that file rather than running the all-files check.

## Upgrade or roll back

1. Stop the MCP server/client connection and close Blender.
2. Download the desired version's wheel from its release page.
3. In the same environment, run `python -m pip install --upgrade ./<wheel-filename>`.
   On Windows, use `.\.venv\Scripts\python.exe` and your downloaded path.
4. Run `better-blender-mcp install-addon --blender-version <your-version>` again,
   or install the matching add-on ZIP manually.
5. Restart Blender, start the bridge, restart the MCP client, and run `doctor`.

For rollback, explicitly install an earlier release's wheel and its matching
add-on using the same steps. Back up `~/.better-blender` first when changing
versions; compatibility of stored state across future versions is not guaranteed.
Installing packages does not intentionally delete your scenes, credentials,
checkpoints or rendered outputs. An old explicit `change-me` token must be replaced
with generated configuration; existing custom tokens must match on both sides.

## Releases versus Actions artifacts

Tagged GitHub Releases provide versioned public download links and release notes.
They do not have the Actions artifact's 30-day expiry (a maintainer can still delete
a release). Untagged CI runs continue to provide temporary development artifacts
under **Actions → run → Artifacts → better-blender-distributions**.
The package is not automatically published to PyPI.
