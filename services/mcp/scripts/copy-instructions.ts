#!/usr/bin/env tsx
/**
 * Copies shared reference files from products/posthog_ai into src/instructions/references/.
 * Run via `pnpm run build:instructions`.
 */
import { cpSync, mkdirSync } from 'fs'
import { resolve } from 'path'

const ROOT_DIR = resolve(__dirname, '..')
const REPO_ROOT = resolve(ROOT_DIR, '../..')
const SRC = resolve(REPO_ROOT, 'products/posthog_ai/skills/query-data/references')
const DEST = resolve(ROOT_DIR, 'src/instructions/references')

mkdirSync(DEST, { recursive: true })
cpSync(SRC, DEST, { recursive: true })
