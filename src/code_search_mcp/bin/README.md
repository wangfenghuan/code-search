# Bundled Standalone ripgrep (rg) Binary

This directory contains precompiled static binaries for **ripgrep**, enabling zero-setup, zero-compilation, out-of-the-box exact code search with SIMD hardware acceleration.

### How it works
1. **Priority 1**: `code-search-mcp` checks this `bin/` directory for `rg.exe` (Windows) or `rg` (Linux/macOS).
2. **Priority 2**: Checks system `PATH` (`shutil.which("rg")`).
3. **Priority 3**: Checks existing IDE installations (VS Code / Cursor `@vscode/ripgrep`).
4. **Fallback**: Gracefully falls back to the built-in pure Python multithreaded regex engine if no binary is found.

### Binary details
- **Windows**: `rg.exe` (ripgrep with PCRE2, AVX2 SIMD hardware acceleration).
