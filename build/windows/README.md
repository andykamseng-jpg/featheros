# Build the self-contained Windows app

The Windows release uses PyInstaller to bundle Python and the Feather agent into `FeatherPrep.exe` and `FeatherMCP.exe`; users do not install Python. Inno Setup packages them as a per-user versioned installer, such as `FeatherOS-Setup-0.6.15.exe`. The release also includes a `FeatherOS-Setup.exe` alias for existing automatic updaters. Setup closes the running Feather Prep window before replacing its files, launches the installed app automatically, then closes without a Finish page. The included GitHub Actions workflow creates the installer and a ZIP artifact. It builds x64 apps for a first modern Windows test target; it is not a compatibility claim for XP, Windows 7, 32-bit Windows, ARM, or every Windows release.

`FeatherPrep.exe` starts a small desktop window, opens the local dashboard, and automatically collects a read-only hardware inventory. It leaves the current Windows installation and disks unchanged. The optional cloud connection asks for an HTTPS endpoint, model, and key; the key remains in process memory and is not written to Feather's files.

`FeatherMCP.exe` is the stdio MCP server for an MCP client configuration. It uses the same local data and editable source folder as Feather Prep.

The default workflow artifact is explicitly labeled **unsigned-development**. Windows Smart App Control blocks unknown, unsigned programs by default, so this artifact is for development only and may not run on the affected Windows 11 PC. A release for protected devices needs a real RSA code-signing certificate from a provider trusted by Windows. To enable the workflow signing step, store the PFX as the repository secret `FEATHER_SIGNING_CERT_BASE64` and its password as `FEATHER_SIGNING_CERT_PASSWORD`; the certificate and password are never included in the artifact. A signature does not make the app a finished or tested FeatherOS operating-system installer.

The workflow can be run with `workflow_dispatch` after the project is in a GitHub repository, or by pushing a `v*` tag. The ZIP is then available under that workflow's Artifacts.
