/**
 * Client-side parsing for drag-and-drop skill uploads.
 *
 * Turns a dropped folder (via the `webkitGetAsEntry` filesystem API) or a
 * `.zip` archive into one or more `ParsedSkill`s ready to POST through
 * `createSkillTemplate`. Each `SKILL.md` found becomes a skill: its
 * directory is the skill root, its frontmatter populates the structured
 * fields, and every sibling file under the root rides along as a companion.
 *
 * Zero-dependency on purpose — folder reads use the browser filesystem API
 * and zip entries are inflated with the built-in `DecompressionStream`, so
 * the console ships no archive/YAML libraries.
 */

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

/* ── Frontmatter parsing (minimal YAML subset) ──────────────────────────── */

interface Frontmatter {
    meta: Record<string, unknown>
    body: string
}

const FRONTMATTER_RE = /^﻿?---\r?\n([\s\S]*?)\r?\n---\r?\n?/

/**
 * Parse a leading `---` frontmatter block. Handles the flat scalar fields
 * and a single-level nested `metadata:` map — the shape `assemble_skill_md`
 * emits. Anything fancier (multi-line scalars, deep nesting) is out of
 * scope; the server re-validates regardless.
 */
export function parseFrontmatter(text: string): Frontmatter {
    const match = FRONTMATTER_RE.exec(text)
    if (!match) {
        return { meta: {}, body: text.replace(/^﻿/, '') }
    }
    const body = text.slice(match[0].length).replace(/^\n+/, '')
    const meta: Record<string, unknown> = {}
    const lines = match[1].split(/\r?\n/)

    for (let i = 0; i < lines.length; i++) {
        const line = lines[i]
        if (!line.trim() || /^\s*#/.test(line) || /^\s/.test(line)) {
            continue // blank, comment, or an indented child consumed below
        }
        const colon = line.indexOf(':')
        if (colon === -1) {
            continue
        }
        const key = line.slice(0, colon).trim()
        const rawValue = line.slice(colon + 1).trim()
        if (rawValue === '') {
            // A nested map — consume following indented `  k: v` lines.
            const nested: Record<string, string> = {}
            while (i + 1 < lines.length && /^\s+\S/.test(lines[i + 1])) {
                const childLine = lines[++i]
                const childColon = childLine.indexOf(':')
                if (childColon === -1) {
                    continue
                }
                nested[childLine.slice(0, childColon).trim()] = unquote(childLine.slice(childColon + 1).trim())
            }
            meta[key] = nested
        } else {
            meta[key] = unquote(rawValue)
        }
    }
    return { meta, body }
}

function unquote(value: string): string {
    if ((value.startsWith('"') && value.endsWith('"')) || (value.startsWith("'") && value.endsWith("'"))) {
        return value.slice(1, -1)
    }
    return value
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

/* ── Zip reading (central directory + DecompressionStream) ──────────────── */

const EOCD_SIG = 0x06054b50
const CDH_SIG = 0x02014b50

/**
 * Inflate a `.zip` into a flat file list. Supports stored + DEFLATE entries.
 *
 * Every offset and size out of the (untrusted) central directory is
 * bounds-checked against the buffer, and each extracted entry is metered
 * through `budget` — so a malformed or zip-bomb archive fails fast instead
 * of reading out of range or inflating without limit.
 */
export async function unzip(file: File, budget: ByteBudget = new ByteBudget()): Promise<UploadFile[]> {
    const buf = new Uint8Array(await file.arrayBuffer())
    const view = new DataView(buf.buffer)
    const eocd = findEocd(view, buf.length)
    if (eocd === -1) {
        throw new Error(`${file.name} is not a readable zip archive.`)
    }

    const count = view.getUint16(eocd + 10, true)
    let ptr = view.getUint32(eocd + 16, true)
    const decoder = new TextDecoder()
    const out: UploadFile[] = []
    const malformed = (): never => {
        throw new Error(`${file.name} is malformed (zip directory points outside the archive).`)
    }

    for (let i = 0; i < count; i++) {
        if (ptr + 46 > buf.length || view.getUint32(ptr, true) !== CDH_SIG) {
            break
        }
        const method = view.getUint16(ptr + 10, true)
        const compSize = view.getUint32(ptr + 20, true)
        const uncompSize = view.getUint32(ptr + 24, true)
        const nameLen = view.getUint16(ptr + 28, true)
        const extraLen = view.getUint16(ptr + 30, true)
        const commentLen = view.getUint16(ptr + 32, true)
        const localOffset = view.getUint32(ptr + 42, true)
        if (ptr + 46 + nameLen > buf.length) {
            malformed()
        }
        const name = decoder.decode(buf.subarray(ptr + 46, ptr + 46 + nameLen))
        ptr += 46 + nameLen + extraLen + commentLen

        if (name.endsWith('/')) {
            continue // directory entry
        }
        // Charge the declared uncompressed size up front so a zip bomb is
        // rejected before we spend CPU inflating it.
        budget.add(uncompSize, name)

        if (localOffset + 30 > buf.length) {
            malformed()
        }
        // Local header: data starts after its own (possibly different) name + extra lengths.
        const localNameLen = view.getUint16(localOffset + 26, true)
        const localExtraLen = view.getUint16(localOffset + 28, true)
        const dataStart = localOffset + 30 + localNameLen + localExtraLen
        if (dataStart + compSize > buf.length) {
            malformed()
        }
        const raw = buf.subarray(dataStart, dataStart + compSize)
        const bytes = method === 0 ? raw : await inflateRaw(raw)
        out.push({ path: name, content: decoder.decode(bytes) })
    }
    return out
}

function findEocd(view: DataView, length: number): number {
    // EOCD is near the end; scan back across the max comment window (64KiB).
    const min = Math.max(0, length - 0xffff - 22)
    for (let i = length - 22; i >= min; i--) {
        if (view.getUint32(i, true) === EOCD_SIG) {
            return i
        }
    }
    return -1
}

async function inflateRaw(bytes: Uint8Array): Promise<Uint8Array> {
    const stream = new Blob([bytes as BlobPart]).stream().pipeThrough(new DecompressionStream('deflate-raw'))
    return new Uint8Array(await new Response(stream).arrayBuffer())
}
