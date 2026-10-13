# DARTS Stream Deck Plugin — Build & Packaging Pipeline

This document describes the reproducible build and packaging pipeline for the self-contained DARTS Stream Deck plugin (`com.pineapplecola.darts`).

## Architecture Overview

Traditional Stream Deck plugins rely on Elgato's managed Node.js runtime located in `%APPDATA%\Elgato\StreamDeck\NodeJS\`. When this directory fails to provision or is empty, Node-based plugins will silently fail to load, reporting manifest missing errors in `StreamDeck.log`.

To guarantee 100% reliability across all machines, the DARTS Stream Deck plugin uses a **self-contained native binary architecture**:
- `CodePathWin`: `bin/darts-plugin.exe` (native Windows PE32+ 64-bit executable).
- `CodePathMac`: `bin/darts-plugin` (native macOS Universal Mach-O binary supporting both Intel `x86_64` and Apple Silicon `arm64`).
- **No managed Node.js dependency**: `manifest.json` deliberately omits the `Nodejs` block.

## Prerequisites

- **Go 1.22+**: For compiling the native binaries.
- **Node.js 18+ & npm**: For orchestrating the build, running regression tests, and executing the `@elgato/cli` tools.

## Repository Layout

- `src_go/`: Go source code implementing the Stream Deck WebSocket protocol, DARTS HTTP polling, state model, and SVG rendering.
  - `src_go/vendor/`: Fully vendored dependencies (e.g. `gorilla/websocket`), enabling completely offline builds without internet access.
- `build.js`: The build script orchestrating Go compilation, cross-compilation, and universal binary assembly.
- `com.pineapplecola.darts.sdPlugin/`: The actual plugin bundle containing the manifest, compiled binaries, property inspector HTML/JS, and action images.
- `dist/com.pineapplecola.darts.streamDeckPlugin`: The committed, prebuilt distribution package (~8 MB).

## Build Commands

From `DARTS/streamdeck/plugin`:

```sh
# 1. Install devDependencies (@elgato/cli)
npm ci

# 2. Compile native executables
npm run build

# 3. Run regression tests and manifest schema validation
npm run validate

# 4. Package the distributable .streamDeckPlugin bundle
npm run pack
```

### Script Details

1. **`npm run build` (`node build.js`)**:
   - Compiles Windows binary:
     `CGO_ENABLED=0 GOOS=windows GOARCH=amd64 go build -mod=vendor -ldflags="-s -w" -o com.pineapplecola.darts.sdPlugin/bin/darts-plugin.exe .`
   - Compiles macOS slices:
     - `darwin/amd64` (Intel)
     - `darwin/arm64` (Apple Silicon)
   - Assembles Universal Mach-O binary:
     `assembleUniversalMachO` combines both slices into `com.pineapplecola.darts.sdPlugin/bin/darts-plugin` using a Mach-O FAT header (`0xcafebabe`, 2 architectures) with 16 KB page alignment (`alignPow = 14`), compatible with macOS dynamic linkers.
2. **`npm run validate` (`npm test && streamdeck validate com.pineapplecola.darts.sdPlugin`)**:
   - Executes `DARTS/tests/streamdeck_plugin_regression.test.js` to assert manifest contracts, state machine invariants, standalone binary headers, canonical naming, and documentation compliance.
   - Invokes `@elgato/cli` (`streamdeck validate`) to check the plugin against Elgato's official manifest schema. Note: The category name warning ("Expected 'DARTS Live Map', but was 'DARTS'") is intentional.
3. **`npm run pack` (`streamdeck pack com.pineapplecola.darts.sdPlugin --output dist --force`)**:
   - Packages the plugin into `dist/com.pineapplecola.darts.streamDeckPlugin`.
   - The produced archive is a standard zip archive with the `.streamDeckPlugin` extension.
   - The prebuilt package is committed to source control so users do not need Go or Node.js to install.
