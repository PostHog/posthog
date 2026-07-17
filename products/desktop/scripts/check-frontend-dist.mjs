/**
 * Packaging preflight: fail fast with instructions when the PostHog frontend
 * has not been built, instead of letting electron-builder produce an app with
 * an empty frontend-dist resource.
 */

import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const distDir = path.resolve(__dirname, '../../../frontend/dist')

if (!fs.existsSync(path.join(distDir, 'preload-manifest.json'))) {
    console.error(`The PostHog frontend is not built (no preload-manifest.json in ${distDir}).`)
    console.error('Run: pnpm --filter=@posthog/frontend build:products && pnpm --filter=@posthog/frontend build')
    process.exit(1)
}
