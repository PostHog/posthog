import type { ReadResourceResult } from '@modelcontextprotocol/sdk/types.js'

import { parseFrontmatterFields, type SkillCatalog } from '@/skills/skill-catalog'

import { hashBytes } from './cache/SharedBlobCache'

export const SKILLS_EXTENSION_ID = 'io.modelcontextprotocol/skills'

const SKILL_URI_SCHEME = 'skill://'
const SKILL_LIST_PAGE_SIZE = 50

interface SkillResourceEntry {
    uri: string
    digest: string
    size: number
}

export interface SkillEntry {
    uri: string
    frontmatter: Record<string, unknown>
    resources: SkillResourceEntry[]
}

export interface SkillListResult {
    skills: SkillEntry[]
    nextCursor?: string
}

/** The URI names no skill or skill file this server serves. The extension maps it to Invalid params. */
export class UnknownSkillResourceError extends Error {
    constructor(uri: string) {
        super(`Unknown skill resource: "${uri}"`)
        this.name = 'UnknownSkillResourceError'
    }
}

interface SkillIndex {
    names: string[]
    entriesByName: Map<string, SkillEntry>
    entriesByUri: Map<string, SkillEntry>
    filesByUri: Map<string, { text: string; mimeType: string }>
}

// A catalog is immutable and replaced whole on refresh, so its digests are computed once.
const indexes = new WeakMap<SkillCatalog, SkillIndex>()

export function isSkillUri(uri: unknown): uri is string {
    return typeof uri === 'string' && uri.startsWith(SKILL_URI_SCHEME)
}

export function listSkills(catalog: SkillCatalog | undefined, cursor?: unknown): SkillListResult {
    if (!catalog) {
        return { skills: [] }
    }
    const { names, entriesByName } = indexFor(catalog)
    // The cursor is the last name of the previous page, so a refresh between pages skips or repeats nothing.
    const start = typeof cursor === 'string' ? names.findIndex((name) => name > cursor) : 0
    const page = start === -1 ? [] : names.slice(start, start + SKILL_LIST_PAGE_SIZE)
    const hasMore = start !== -1 && start + page.length < names.length
    return {
        skills: page.map((name) => entriesByName.get(name)!),
        ...(hasMore ? { nextCursor: page.at(-1)! } : {}),
    }
}

export function getSkill(catalog: SkillCatalog | undefined, uri: unknown): { skill: SkillEntry } {
    const skill = catalog && typeof uri === 'string' ? indexFor(catalog).entriesByUri.get(uri) : undefined
    if (!skill) {
        throw new UnknownSkillResourceError(String(uri))
    }
    return { skill }
}

export function readSkillFile(catalog: SkillCatalog | undefined, uri: string): ReadResourceResult {
    const file = catalog ? indexFor(catalog).filesByUri.get(uri) : undefined
    if (!file) {
        throw new UnknownSkillResourceError(uri)
    }
    return { contents: [{ uri, mimeType: file.mimeType, text: file.text }] }
}

function indexFor(catalog: SkillCatalog): SkillIndex {
    let index = indexes.get(catalog)
    if (!index) {
        index = buildIndex(catalog)
        indexes.set(catalog, index)
    }
    return index
}

function buildIndex(catalog: SkillCatalog): SkillIndex {
    const encoder = new TextEncoder()
    const index: SkillIndex = {
        names: catalog.listNames().sort(),
        entriesByName: new Map(),
        entriesByUri: new Map(),
        filesByUri: new Map(),
    }
    for (const name of index.names) {
        const skill = catalog.get(name)!
        const skillFile = skill.files.find((file) => file.path === 'SKILL.md')!
        const entry: SkillEntry = {
            uri: skillFileUri(name, 'SKILL.md'),
            frontmatter: parseFrontmatterFields(skillFile.content, `${name}/SKILL.md`),
            resources: skill.files.map((file) => {
                const uri = skillFileUri(name, file.path)
                const bytes = encoder.encode(file.content)
                index.filesByUri.set(uri, {
                    text: file.content,
                    mimeType: file.kind === 'markdown' ? 'text/markdown' : 'text/plain',
                })
                return { uri, digest: `sha256:${hashBytes(bytes)}`, size: bytes.byteLength }
            }),
        }
        index.entriesByName.set(name, entry)
        index.entriesByUri.set(entry.uri, entry)
    }
    return index
}

function skillFileUri(name: string, path: string): string {
    return `${SKILL_URI_SCHEME}${name}/${path.split('/').map(encodeURIComponent).join('/')}`
}
