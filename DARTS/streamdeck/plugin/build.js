#!/usr/bin/env node
'use strict';

const { execFileSync } = require('child_process');
const fs = require('fs');
const os = require('os');
const path = require('path');

const pluginRoot = __dirname;
const srcGo = path.join(pluginRoot, 'src_go');
const binDir = path.join(pluginRoot, 'com.pineapplecola.darts.sdPlugin', 'bin');

if (!fs.existsSync(binDir)) {
    fs.mkdirSync(binDir, { recursive: true });
}

function runGoBuild(goos, goarch, outputPath) {
    const env = {
        ...process.env,
        CGO_ENABLED: '0',
        GOOS: goos,
        GOARCH: goarch,
    };
    execFileSync('go', ['build', '-mod=vendor', '-ldflags=-s -w', '-o', outputPath, '.'], {
        cwd: srcGo,
        env,
        stdio: 'inherit',
    });
}

function assembleUniversalMachO(amd64Path, arm64Path, universalPath) {
    const dataAmd64 = fs.readFileSync(amd64Path);
    const dataArm64 = fs.readFileSync(arm64Path);

    const alignPow = 14; // 16 KB page alignment for arm64
    const alignBytes = 1 << alignPow;

    const offset0 = alignBytes;
    const size0 = dataAmd64.length;

    const offset1 = Math.ceil((offset0 + size0) / alignBytes) * alignBytes;
    const size1 = dataArm64.length;

    const totalSize = offset1 + size1;
    const buf = Buffer.alloc(totalSize);

    // Fat Header: magic = 0xcafebabe, nfat_arch = 2
    buf.writeUInt32BE(0xcafebabe, 0);
    buf.writeUInt32BE(2, 4);

    // Arch 0: x86_64 (cputype=0x01000007, cpusubtype=3, offset, size, align)
    buf.writeUInt32BE(0x01000007, 8);
    buf.writeUInt32BE(3, 12);
    buf.writeUInt32BE(offset0, 16);
    buf.writeUInt32BE(size0, 20);
    buf.writeUInt32BE(alignPow, 24);

    // Arch 1: arm64 (cputype=0x0100000c, cpusubtype=0, offset, size, align)
    buf.writeUInt32BE(0x0100000c, 28);
    buf.writeUInt32BE(0, 32);
    buf.writeUInt32BE(offset1, 36);
    buf.writeUInt32BE(size1, 40);
    buf.writeUInt32BE(alignPow, 44);

    dataAmd64.copy(buf, offset0);
    dataArm64.copy(buf, offset1);

    fs.writeFileSync(universalPath, buf);
    fs.chmodSync(universalPath, 0o755);
}

function main() {
    console.log('[build] Compiling standalone DARTS Stream Deck plugin binaries...');
    const winExe = path.join(binDir, 'darts-plugin.exe');
    console.log(`[build] Building Windows binary: ${winExe}`);
    runGoBuild('windows', 'amd64', winExe);

    const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'darts-build-'));
    try {
        const macAmd64 = path.join(tmpDir, 'darts-mac-amd64');
        const macArm64 = path.join(tmpDir, 'darts-mac-arm64');
        const macUniversal = path.join(binDir, 'darts-plugin');

        console.log('[build] Building macOS amd64 slice...');
        runGoBuild('darwin', 'amd64', macAmd64);
        console.log('[build] Building macOS arm64 slice...');
        runGoBuild('darwin', 'arm64', macArm64);

        console.log(`[build] Assembling universal macOS binary: ${macUniversal}`);
        assembleUniversalMachO(macAmd64, macArm64, macUniversal);

        const winStat = fs.statSync(winExe);
        const macStat = fs.statSync(macUniversal);
        console.log(`[build] Successfully built:`);
        console.log(`  - Windows: ${winExe} (${(winStat.size / (1024 * 1024)).toFixed(2)} MB)`);
        console.log(`  - macOS:   ${macUniversal} (${(macStat.size / (1024 * 1024)).toFixed(2)} MB)`);
    } finally {
        fs.rmSync(tmpDir, { recursive: true, force: true });
    }
}

if (require.main === module) {
    main();
}

module.exports = { assembleUniversalMachO, runGoBuild };
