/**
 * Downloads the Electron binary on demand. This repo's pnpm setup does not run
 * dependency postinstall scripts, so `pnpm install` leaves the electron package
 * without its binary; this script runs electron's own install.js exactly once.
 */

import { spawnSync } from 'node:child_process'
import fs from 'node:fs'
import { createRequire } from 'node:module'
import path from 'node:path'

const require = createRequire(import.meta.url)
const electronDir = path.dirname(require.resolve('electron/package.json'))
const pathFile = path.join(electronDir, 'path.txt')

if (fs.existsSync(pathFile) && fs.existsSync(path.join(electronDir, 'dist'))) {
    process.exit(0)
}

console.info('Downloading the Electron binary (first run only)...')
const result = spawnSync(process.execPath, ['install.js'], { cwd: electronDir, stdio: 'inherit' })
process.exit(result.status ?? 1)
