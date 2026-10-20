# Bundled Standalone ripgrep (rg) Binaries

This directory contains precompiled static binaries for **ripgrep**, enabling zero-setup, zero-compilation, out-of-the-box exact code search with SIMD hardware acceleration across Windows, macOS, and Linux.

### Platform Binaries

| Operating System | Architecture | Binary File | Details |
|---|---|---|---|
| **Windows** | x86_64 | `rg.exe` | PCRE2, AVX2 SIMD hardware acceleration |
| **Linux** | x86_64 | `rg-x86_64-unknown-linux-musl` | Statically linked with MUSL (zero glibc dependency, works on Alpine, Ubuntu, Debian, CentOS, Arch, and Docker) |
| **Linux** | ARM64 / aarch64 | `rg-aarch64-unknown-linux-gnu` | 64-bit ARM Linux (AWS Graviton, Raspberry Pi 4/5, Docker on Apple Silicon) |
| **macOS** | Apple Silicon (arm64) | `rg-aarch64-apple-darwin` | macOS M1 / M2 / M3 / M4 |
| **macOS** | Intel (x86_64) | `rg-x86_64-apple-darwin` | macOS Intel 64-bit |
| **POSIX Fallback**| Generic | `rg` | Default symlink/copy fallback for POSIX environments |

### Resolution Priority

1. **Priority 1**: Architectural match from this `bin/` directory.
2. **Priority 2**: System `PATH` (`shutil.which("rg")`).
3. **Priority 3**: Homebrew (`/opt/homebrew/bin/rg`, `/usr/local/bin/rg`) or Cargo (`~/.cargo/bin/rg`).
4. **Priority 4**: IDE bundled binaries (VS Code / Cursor `@vscode/ripgrep`).
5. **Fallback**: Gracefully falls back to the built-in pure Python multithreaded regex searcher if no binary is found.
