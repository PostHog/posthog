#!/usr/bin/env tsx
/**
 * Copies shared prompt files.
 */
import { cpSync, mkdirSync } from 'fs'
import { dirname, resolve } from 'path'

const ROOT_DIR = resolve(__dirname, '..')
const REPO_ROOT = resolve(ROOT_DIR, '../..')

const PROMPTS = [
    {
        src: 'products/posthog_ai/skills/query-examples/references/guidelines.md',
        dest: 'shared/guidelines.md',
    },
]

for (const prompt of PROMPTS) {
    const src = resolve(REPO_ROOT, prompt.src)
    const dest = resolve(ROOT_DIR, prompt.dest)
    mkdirSync(dirname(dest), { recursive: true })
    cpSync(src, dest, { recursive: true })
}
