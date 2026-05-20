#!/usr/bin/env tsx
/**
 * Copies shared prompt files.
 */
import { cpSync, mkdirSync, rmSync } from 'fs'
import { dirname, resolve } from 'path'

const ROOT_DIR = resolve(__dirname, '..')
const REPO_ROOT = resolve(ROOT_DIR, '../..')

const PROMPTS = [
    {
        src: 'products/posthog_ai/skills/querying-posthog-data/references/guidelines.md',
        dest: 'shared/guidelines.md',
    },
]

for (const prompt of PROMPTS) {
    const src = resolve(REPO_ROOT, prompt.src)
    const dest = resolve(ROOT_DIR, prompt.dest)
    mkdirSync(dirname(dest), { recursive: true })
    // Belt-and-braces: Node 24's `cpSync` has been observed to throw EEXIST
    // even with `force: true` on some platforms (notably macOS). Explicitly
    // remove the dest first so watch-mode rebuilds always succeed.
    rmSync(dest, { force: true, recursive: true })
    cpSync(src, dest, { recursive: true, force: true })
}
