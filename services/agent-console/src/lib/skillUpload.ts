/**
 * Client-side parsing for drag-and-drop skill uploads.
 *
 * Turns a dropped folder (via the `webkitGetAsEntry` filesystem API) or a
 * `.zip` archive into one or more `ParsedSkill`s ready to POST through
 * `createSkillTemplate`. Each `SKILL.md` found becomes a skill: its
 * directory is the skill root, its frontmatter populates the structured
 * fields, and every sibling file under the root rides along as a companion.
 *
 * Folder reads use the browser filesystem API (`webkitGetAsEntry`); zip
 * extraction uses `fflate` and frontmatter parsing uses `js-yaml` — both
 * battle-tested, so we don't hand-roll an archive reader or a YAML parser.
 */

import { unzipSync } from 'fflate'
import { load as loadYaml } from 'js-yaml'

import type { SkillTemplateCreateApi } from '@/generated/agent-stack.api.schemas'

export interface UploadFile {
    /** POSIX path relative to the dropped root (e.g. `research/references/deep.md`). */
    path: string
    content: string
}

export interface ParsedSkill {
    /** Spec name — frontmatter `name`, falling back to the skill folder name. */
    name: string
    description: string
    license: string
    compatibility: string
    metadata: Record<string, string>
    allowedTools: string[]
    /** SKILL.md body with its frontmatter stripped. */
    body: string
    /** Companion files, paths relative to the skill folder. */
    files: { path: string; content: string }[]
}

const SKILL_MD = 'SKILL.md'

// Client-side guards against a hostile or fat-fingered drop. These mirror the
// server's per-file cap and keep a single drop from OOMing the tab before the
// API ever rejects it. Tuned a bit above the server limits so a legitimate
// drop fails on the server (with its precise message) rather than here.
const MAX_FILE_BYTES = 2_000_000 // per extracted file
const MAX_TOTAL_BYTES = 50_000_000 // total bytes read across the whole drop
const MAX_FILES = 500 // total file entries across the whole drop

class UploadLimitError extends Error {}

class ByteBudget {
    private total = 0
    private count = 0

    add(bytes: number, label: string): void {
        if (bytes > MAX_FILE_BYTES) {
            throw new UploadLimitError(`${label} exceeds the ${MAX_FILE_BYTES.toLocaleString()}-byte per-file limit.`)
        }
        this.total += bytes
        this.count += 1
        if (this.count > MAX_FILES) {
            throw new UploadLimitError(`Too many files in one drop (limit ${MAX_FILES}).`)
        }
        if (this.total > MAX_TOTAL_BYTES) {
            throw new UploadLimitError(`Drop exceeds the ${MAX_TOTAL_BYTES.toLocaleString()}-byte total limit.`)
        }
    }
}

/** Convert a `ParsedSkill` into the registry create payload. */
export function toCreateBody(skill: ParsedSkill): SkillTemplateCreateApi {
    return {
        name: skill.name,
        description: skill.description,
        body: skill.body,
        license: skill.license || undefined,
        compatibility: skill.compatibility || undefined,
        metadata: Object.keys(skill.metadata).length ? skill.metadata : undefined,
        allowed_tools: skill.allowedTools.length ? skill.allowedTools : undefined,
        // The generated create type reuses the read file shape (with a
        // server-assigned read-only `id`); on input the backend ignores it.
        files: skill.files as SkillTemplateCreateApi['files'],
    }
}

/* ── Drop handling ──────────────────────────────────────────────────────── */

/**
 * Read everything a drop carried into a flat file list. Directories are
 * walked recursively; `.zip` files are inflated; loose files pass through.
 */
export async function readDataTransfer(dt: DataTransfer): Promise<UploadFile[]> {
    const out: UploadFile[] = []
    const budget = new ByteBudget()
    const items = Array.from(dt.items)
    // Snapshot entries first — `DataTransferItemList` is invalidated once we await.
    const entries = items.map((it) => (it.kind === 'file' && it.webkitGetAsEntry ? it.webkitGetAsEntry() : null))

    for (let i = 0; i < items.length; i++) {
        const entry = entries[i]
        if (entry?.isDirectory) {
            out.push(...(await readDirectoryEntry(entry as FileSystemDirectoryEntry, entry.name, budget)))
            continue
        }
        const file = items[i].getAsFile()
        if (!file) {
            continue
        }
        if (isZip(file)) {
            out.push(...(await unzip(file, budget)))
        } else {
            const path = entry?.fullPath?.replace(/^\//, '') ?? file.name
            budget.add(file.size, path)
            out.push({ path, content: await file.text() })
        }
    }
    return out
}

function isZip(file: File): boolean {
    return file.type === 'application/zip' || file.name.toLowerCase().endsWith('.zip')
}

async function readDirectoryEntry(
    dir: FileSystemDirectoryEntry,
    prefix: string,
    budget: ByteBudget
): Promise<UploadFile[]> {
    const out: UploadFile[] = []
    for (const child of await readEntries(dir)) {
        const childPath = `${prefix}/${child.name}`
        if (child.isDirectory) {
            out.push(...(await readDirectoryEntry(child as FileSystemDirectoryEntry, childPath, budget)))
        } else {
            const file = await fileOf(child as FileSystemFileEntry)
            budget.add(file.size, childPath)
            out.push({ path: childPath, content: await file.text() })
        }
    }
    return out
}

function readEntries(dir: FileSystemDirectoryEntry): Promise<FileSystemEntry[]> {
    // `readEntries` returns results in batches — keep calling until it drains.
    const reader = dir.createReader()
    const all: FileSystemEntry[] = []
    return new Promise((resolve, reject) => {
        const pump = (): void => {
            reader.readEntries((batch) => {
                if (batch.length === 0) {
                    resolve(all)
                    return
                }
                all.push(...batch)
                pump()
            }, reject)
        }
        pump()
    })
}

function fileOf(entry: FileSystemFileEntry): Promise<File> {
    return new Promise((resolve, reject) => entry.file(resolve, reject))
}

/* ── Skill assembly ─────────────────────────────────────────────────────── */

/**
 * Group a flat file list into skills, one per `SKILL.md`. Throws if no
 * `SKILL.md` is present so the caller can show a clear message.
 */
export function buildSkills(files: UploadFile[]): ParsedSkill[] {
    const indexes = files.filter((f) => baseName(f.path) === SKILL_MD)
    if (indexes.length === 0) {
        throw new Error('No SKILL.md found. Drop a skill folder (or zip) containing a SKILL.md at its root.')
    }

    return indexes.map((index) => {
        const root = dirName(index.path)
        const { meta, body } = parseFrontmatter(index.content)
        const companions = files
            .filter((f) => f !== index && underRoot(f.path, root))
            .map((f) => ({ path: relativeTo(f.path, root), content: f.content }))

        return {
            name: stringField(meta.name) || baseName(root) || '',
            description: stringField(meta.description),
            license: stringField(meta.license),
            compatibility: stringField(meta.compatibility),
            metadata: stringMap(meta.metadata),
            allowedTools: toolList(meta['allowed-tools']),
            body,
            files: companions,
        }
    })
}

function underRoot(path: string, root: string): boolean {
    return root === '' ? true : path === root || path.startsWith(`${root}/`)
}

function relativeTo(path: string, root: string): string {
    return root === '' ? path : path.slice(root.length + 1)
}

function baseName(path: string): string {
    const i = path.lastIndexOf('/')
    return i === -1 ? path : path.slice(i + 1)
}

function dirName(path: string): string {
    const i = path.lastIndexOf('/')
    return i === -1 ? '' : path.slice(0, i)
}

/* ── Frontmatter parsing ────────────────────────────────────────────────── */

interface Frontmatter {
    meta: Record<string, unknown>
    body: string
}

const FRONTMATTER_RE = /^﻿?---\r?\n([\s\S]*?)\r?\n---\r?\n?/

/**
 * Split a leading `---` YAML frontmatter block off the body and parse it
 * with `js-yaml`. Malformed frontmatter parses to empty metadata — the
 * server re-validates the structured fields regardless.
 */
export function parseFrontmatter(text: string): Frontmatter {
    const match = FRONTMATTER_RE.exec(text)
    if (!match) {
        return { meta: {}, body: text.replace(/^﻿/, '') }
    }
    const body = text.slice(match[0].length).replace(/^\n+/, '')
    let meta: Record<string, unknown> = {}
    try {
        const parsed = loadYaml(match[1])
        if (parsed && typeof parsed === 'object') {
            meta = parsed as Record<string, unknown>
        }
    } catch {
        // Invalid YAML — fall back to no metadata.
    }
    return { meta, body }
}

function stringField(value: unknown): string {
    return typeof value === 'string' ? value : ''
}

function stringMap(value: unknown): Record<string, string> {
    if (!value || typeof value !== 'object') {
        return {}
    }
    const out: Record<string, string> = {}
    for (const [k, v] of Object.entries(value as Record<string, unknown>)) {
        out[k] = typeof v === 'string' ? v : String(v)
    }
    return out
}

function toolList(value: unknown): string[] {
    if (Array.isArray(value)) {
        return value.map(String)
    }
    if (typeof value === 'string') {
        return value.split(/\s+/).filter(Boolean)
    }
    return []
}

/* ── Zip reading (fflate) ────────────────────────────────────────────────── */

/**
 * Inflate a `.zip` into a flat file list via `fflate`. The compressed input
 * is bounded up front, the per-file `filter` skips directory entries and any
 * entry whose declared uncompressed size already blows the per-file cap, and
 * each extracted entry's real size is metered through `budget`.
 */
export async function unzip(file: File, budget: ByteBudget = new ByteBudget()): Promise<UploadFile[]> {
    if (file.size > MAX_TOTAL_BYTES) {
        throw new UploadLimitError(`${file.name} exceeds the ${MAX_TOTAL_BYTES.toLocaleString()}-byte archive limit.`)
    }
    const data = new Uint8Array(await file.arrayBuffer())
    let entries: Record<string, Uint8Array>
    try {
        entries = unzipSync(data, {
            filter: (f) => !f.name.endsWith('/') && f.originalSize <= MAX_FILE_BYTES,
        })
    } catch {
        throw new Error(`${file.name} is not a readable zip archive.`)
    }
    const decoder = new TextDecoder()
    const out: UploadFile[] = []
    for (const [name, bytes] of Object.entries(entries)) {
        budget.add(bytes.byteLength, name)
        out.push({ path: name, content: decoder.decode(bytes) })
    }
    return out
}
