import { strFromU8, unzipSync } from 'fflate'
import { parse as parseYaml } from 'yaml'

export const LEARN_OUTPUT_CHAR_LIMIT = 44_000

const MAX_GLOBAL_SKILLS = 10
const MAX_GLOBAL_SNIPPETS = 2
const MAX_SCOPED_MATCHES = 50
const SEARCH_CONTEXT_LINES = 2
const MAX_ARCHIVE_FILES = 5_000
const MAX_ARCHIVE_FILE_BYTES = 8 * 1024 * 1024
const MAX_ARCHIVE_UNCOMPRESSED_BYTES = 64 * 1024 * 1024

type SkillFileKind = 'markdown' | 'script' | 'other'

export interface SkillFile {
    path: string
    content: string
    lineCount: number
    charCount: number
    kind: SkillFileKind
}

export interface SkillDefinition {
    name: string
    description: string
    files: readonly SkillFile[]
}

export interface SkillManifestEntry {
    path: string
    lineCount?: number
    charCount?: number
}

export interface LearnSearchSnippet {
    path: string
    line: number
    text: string
}

export interface LearnSearchResult {
    identifier: string
    description: string
    snippets: LearnSearchSnippet[]
}

interface RankedSkill {
    skill: SkillDefinition
    score: number
    snippets: LearnSearchSnippet[]
}

/**
 * Runtime view of the published product skill bundle. The bundle is parsed
 * once per refresh; all learn operations use this in-memory representation.
 */
export class SkillCatalog {
    private readonly skillsByName: Map<string, SkillDefinition>

    constructor(skills: readonly SkillDefinition[]) {
        this.skillsByName = new Map()
        for (const skill of skills) {
            if (this.skillsByName.has(skill.name)) {
                throw new Error(`Duplicate skill name: "${skill.name}"`)
            }
            this.skillsByName.set(skill.name, skill)
        }
    }

    static fromZip(bytes: Uint8Array): SkillCatalog {
        let fileCount = 0
        let totalUncompressedBytes = 0
        const archive = unzipSync(bytes, {
            filter: (file) => {
                if (file.name.endsWith('/')) {
                    return false
                }
                validateArchivePath(file.name)
                fileCount += 1
                totalUncompressedBytes += file.originalSize
                if (
                    fileCount > MAX_ARCHIVE_FILES ||
                    file.originalSize > MAX_ARCHIVE_FILE_BYTES ||
                    totalUncompressedBytes > MAX_ARCHIVE_UNCOMPRESSED_BYTES
                ) {
                    throw new Error('Skill archive exceeds the extraction limit')
                }
                return true
            },
        })
        const filesByDirectory = new Map<string, SkillFile[]>()

        for (const [archivePath, fileBytes] of Object.entries(archive)) {
            if (archivePath.endsWith('/')) {
                continue
            }
            const pathParts = validateArchivePath(archivePath)
            const directory = pathParts[0]!
            const relativePath = pathParts.slice(1).join('/')
            const content = normalizeText(strFromU8(fileBytes))
            if (content.includes('\0')) {
                throw new Error(`Skill archive contains a binary file: "${archivePath}"`)
            }

            const files = filesByDirectory.get(directory) ?? []
            if (files.some((file) => file.path === relativePath)) {
                throw new Error(`Duplicate skill file path: "${archivePath}"`)
            }
            files.push(makeSkillFile(relativePath, content))
            filesByDirectory.set(directory, files)
        }

        const skills = [...filesByDirectory.entries()].map(([directory, files]) => {
            const skillFile = files.find((file) => file.path === 'SKILL.md')
            if (!skillFile) {
                throw new Error(`Skill archive entry "${directory}" has no SKILL.md`)
            }
            const metadata = parseFrontmatter(skillFile.content, `${directory}/SKILL.md`)
            if (metadata.name === 'skills') {
                throw new Error('Skill name "skills" is reserved by the learn command')
            }
            return {
                name: metadata.name,
                description: metadata.description,
                files: files.sort((left, right) => compareSkillPaths(left.path, right.path)),
            }
        })

        if (skills.length === 0) {
            throw new Error('Skill archive contains no skills')
        }
        return new SkillCatalog(skills.sort((left, right) => left.name.localeCompare(right.name)))
    }

    get size(): number {
        return this.skillsByName.size
    }

    listNames(): string[] {
        return [...this.skillsByName.keys()].sort((left, right) => left.localeCompare(right))
    }

    has(name: string): boolean {
        return this.skillsByName.has(name)
    }

    searchResults(query: string, namespace = ''): LearnSearchResult[] {
        const normalizedQuery = normalizeQuery(query)
        return [...this.skillsByName.values()]
            .map((skill) => rankSkill(skill, normalizedQuery))
            .filter((result): result is RankedSkill => result !== null)
            .sort((left, right) => right.score - left.score || left.skill.name.localeCompare(right.skill.name))
            .slice(0, MAX_GLOBAL_SKILLS)
            .map(({ skill, snippets }) => ({
                identifier: `${namespace}${skill.name}`,
                description: skill.description,
                snippets,
            }))
    }

    search(query: string, namespace = ''): string {
        const results = this.searchResults(query, namespace)

        if (results.length === 0) {
            return `No skills matched "${query}".`
        }
        return formatLearnSearchResults(results)
    }

    read(name: string, path?: string, identifier = name): string {
        const skill = this.requireSkill(name)
        if (path) {
            const file = this.requireFile(skill, path, identifier)
            return formatLearnFile(identifier, file)
        }

        const skillFile = this.requireFile(skill, 'SKILL.md')
        return formatLearnDocument(identifier, skill.description, skillFile, skill.files)
    }

    searchFile(name: string, path: string, query: string, identifier = name): string {
        const skill = this.requireSkill(name)
        const file = this.requireFile(skill, path, identifier)
        return searchLearnFile(identifier, file, query)
    }

    readLines(name: string, path: string, start: number, end: number, identifier = name): string {
        const skill = this.requireSkill(name)
        const file = this.requireFile(skill, path, identifier)
        return readLearnLines(identifier, file, start, end)
    }

    private requireSkill(name: string): SkillDefinition {
        const skill = this.skillsByName.get(name)
        if (!skill) {
            throw new Error(`Unknown skill: "${name}". Use \`learn -s <query>\` to find a skill.`)
        }
        return skill
    }

    private requireFile(skill: SkillDefinition, path: string, identifier = skill.name): SkillFile {
        validateRelativePath(path)
        const file = skill.files.find((candidate) => candidate.path === path)
        if (!file) {
            throw new Error(
                `Unknown file: "${path}" in skill "${identifier}". Run \`learn ${identifier}\` for its manifest.`
            )
        }
        return file
    }
}

const FRONTMATTER_PATTERN = /^---\n([\s\S]*?)\n---(?:\n|$)/

function parseFrontmatter(content: string, source: string): { name: string; description: string } {
    const match = content.match(FRONTMATTER_PATTERN)
    if (!match?.[1]) {
        throw new Error(`Missing YAML frontmatter in "${source}"`)
    }
    const parsed: unknown = parseYaml(match[1])
    if (!isRecord(parsed) || typeof parsed.name !== 'string' || typeof parsed.description !== 'string') {
        throw new Error(`Invalid name or description in "${source}" frontmatter`)
    }
    const name = parsed.name.trim()
    const description = parsed.description.trim()
    if (!name || !description || !/^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(name)) {
        throw new Error(`Invalid skill metadata in "${source}"`)
    }
    return { name, description }
}

function validateArchivePath(path: string): string[] {
    if (!path || path.startsWith('/') || path.includes('\\') || path.includes('\0')) {
        throw new Error(`Unsafe skill archive path: "${path}"`)
    }
    const parts = path.split('/')
    if (parts.length < 2 || parts.some((part) => !part || part === '.' || part === '..')) {
        throw new Error(`Unsafe skill archive path: "${path}"`)
    }
    return parts
}

function validateRelativePath(path: string): void {
    if (!path || path.startsWith('/') || path.includes('\\') || path.includes('\0')) {
        throw new Error(`Unsafe skill path: "${path}"`)
    }
    const parts = path.split('/')
    if (parts.some((part) => !part || part === '.' || part === '..')) {
        throw new Error(`Unsafe skill path: "${path}"`)
    }
}

export function makeSkillFile(path: string, content: string, contentType?: string): SkillFile {
    const kind: SkillFileKind =
        path.toLowerCase().endsWith('.md') || contentType?.toLowerCase().includes('markdown')
            ? 'markdown'
            : path === 'scripts' || path.startsWith('scripts/')
              ? 'script'
              : 'other'
    return {
        path,
        content,
        lineCount: splitLines(content).length,
        charCount: content.length,
        kind,
    }
}

function compareSkillPaths(left: string, right: string): number {
    if (left === 'SKILL.md') {
        return -1
    }
    if (right === 'SKILL.md') {
        return 1
    }
    return left.localeCompare(right)
}

// The read output deliberately avoids Markdown structure: the embedded skill
// content is itself Markdown, so wrapper headings would collide with its own.
function formatManifest(files: readonly SkillManifestEntry[]): string {
    const lines = files.map((file) =>
        file.lineCount === undefined || file.charCount === undefined
            ? `- ${file.path}`
            : `- ${file.path} (${file.lineCount} lines, ${file.charCount} chars)`
    )
    return `Files:\n${lines.join('\n')}`
}

function stripFrontmatter(content: string): string {
    return content.replace(FRONTMATTER_PATTERN, '').replace(/^\n+/, '')
}

export function formatLearnDocument(
    identifier: string,
    description: string,
    skillFile: SkillFile,
    manifestFiles: readonly SkillManifestEntry[]
): string {
    const manifest = formatManifest(manifestFiles)
    const full = `Skill: ${identifier}\nDescription: ${description}\n\n${manifest}\n\nSKILL.md content (frontmatter omitted):\n\n${stripFrontmatter(skillFile.content)}`
    if (full.length <= LEARN_OUTPUT_CHAR_LIMIT) {
        return full
    }
    return formatOversizedFile(identifier, skillFile, manifest)
}

export function formatLearnFile(identifier: string, file: SkillFile): string {
    const header = `File: ${identifier}/${file.path} (${file.lineCount} lines, ${file.charCount} chars)`
    const full = `${header}\n\n${file.content}`
    if (full.length <= LEARN_OUTPUT_CHAR_LIMIT) {
        return full
    }
    return formatOversizedFile(identifier, file)
}

function formatOversizedFile(identifier: string, file: SkillFile, manifest?: string): string {
    const headings = splitLines(file.content)
        .map((line, index) => ({ line, number: index + 1 }))
        .filter(({ line }) => /^#{1,6}\s+/.test(line))
        .map(({ line, number }) => `${number}: ${line}`)
    const outline = headings.length > 0 ? headings.join('\n') : '(No Markdown headings found.)'
    const scope = manifest ? `${manifest}\n\n` : ''
    return fitLearnOutput(
        `File: ${identifier}/${file.path} (${file.lineCount} lines, ${file.charCount} chars)\nThis file is too large to return in full. Use \`learn ${identifier} ${file.path} -s <query>\` or \`learn ${identifier} ${file.path} --lines <start>:<end>\`.\n\n${scope}Heading outline:\n${outline}`
    )
}

export function searchLearnFile(identifier: string, file: SkillFile, query: string): string {
    if (file.kind !== 'markdown') {
        throw new Error('Only Markdown contents are searchable. Read the file directly or use --lines instead.')
    }

    const normalizedQuery = normalizeQuery(query)
    const lines = splitLines(file.content)
    const matchingLines = lines
        .map((line, index) => ({ line, index }))
        .filter(({ line }) => matchesQuery(line, normalizedQuery))
        .slice(0, MAX_SCOPED_MATCHES)

    if (matchingLines.length === 0) {
        return `No matches for "${query}" in ${identifier}/${file.path}.`
    }

    const blocks = matchingLines.map(({ index }) => {
        const start = Math.max(0, index - SEARCH_CONTEXT_LINES)
        const end = Math.min(lines.length - 1, index + SEARCH_CONTEXT_LINES)
        return lines
            .slice(start, end + 1)
            .map((line, offset) => `${start + offset + 1}: ${line}`)
            .join('\n')
    })
    return fitLearnOutput(`Matches in ${identifier}/${file.path}:\n\n${blocks.join('\n\n')}`)
}

export function readLearnLines(identifier: string, file: SkillFile, start: number, end: number): string {
    const lines = splitLines(file.content)
    if (!Number.isInteger(start) || !Number.isInteger(end) || start < 1 || end < start || end > lines.length) {
        throw new Error(`Invalid line range ${start}:${end}. ${identifier}/${file.path} has ${lines.length} lines.`)
    }

    const body = lines
        .slice(start - 1, end)
        .map((line, index) => `${start + index}: ${line}`)
        .join('\n')
    const result = `File: ${identifier}/${file.path} lines ${start}:${end}\n\n${body}`
    if (result.length > LEARN_OUTPUT_CHAR_LIMIT) {
        throw new Error(
            `Requested line range is ${result.length} characters. Narrow it to at most ${LEARN_OUTPUT_CHAR_LIMIT} characters.`
        )
    }
    return result
}

export function formatLearnSearchResults(results: readonly LearnSearchResult[]): string {
    const sections = results.map(({ identifier, description, snippets }) => {
        const lines = [`## ${identifier}`, '', description]
        if (snippets.length > 0) {
            lines.push('', ...snippets.map((snippet) => `${snippet.path}:${snippet.line}: ${snippet.text}`))
        }
        return lines.join('\n')
    })
    return fitLearnOutput(sections.join('\n\n'))
}

function rankSkill(skill: SkillDefinition, query: NormalizedQuery): RankedSkill | null {
    let score = scoreText(skill.name, query, 1_000) + scoreText(skill.description, query, 300)
    const snippets: LearnSearchSnippet[] = []

    for (const file of skill.files) {
        score += scoreText(file.path, query, 120)
        if (file.kind !== 'markdown') {
            continue
        }
        const contentWeight = file.path === 'SKILL.md' ? 80 : 40
        score += scoreText(file.content, query, contentWeight)
        if (snippets.length < MAX_GLOBAL_SNIPPETS) {
            const snippet = findSnippet(file, query)
            if (snippet) {
                snippets.push(snippet)
            }
        }
    }

    return score > 0 ? { skill, score, snippets } : null
}

interface NormalizedQuery {
    phrase: string
    tokens: string[]
}

function normalizeQuery(query: string): NormalizedQuery {
    const phrase = query.trim().toLowerCase()
    if (!phrase) {
        throw new Error('Search query cannot be empty.')
    }
    const tokens = [...new Set(phrase.match(/[\p{L}\p{N}]+/gu) ?? [])]
    if (tokens.length === 0) {
        throw new Error('Search query must contain a letter or number.')
    }
    return { phrase, tokens }
}

function scoreText(text: string, query: NormalizedQuery, weight: number): number {
    const normalizedText = text.toLowerCase()
    let score = normalizedText.includes(query.phrase) ? weight * 2 : 0
    const matchingTokens = query.tokens.filter((token) => normalizedText.includes(token)).length
    if (matchingTokens === query.tokens.length) {
        score += weight
    } else {
        score += matchingTokens * Math.max(1, Math.floor(weight / query.tokens.length / 4))
    }
    return score
}

function matchesQuery(text: string, query: NormalizedQuery): boolean {
    const normalizedText = text.toLowerCase()
    return normalizedText.includes(query.phrase) || query.tokens.every((token) => normalizedText.includes(token))
}

function findSnippet(file: SkillFile, query: NormalizedQuery): LearnSearchSnippet | undefined {
    const lines = splitLines(file.content)
    const index = lines.findIndex((line) => matchesQuery(line, query))
    if (index === -1) {
        return undefined
    }
    return { path: file.path, line: index + 1, text: lines[index]!.trim() }
}

export function fitLearnOutput(value: string): string {
    if (value.length <= LEARN_OUTPUT_CHAR_LIMIT) {
        return value
    }
    const suffix = '\n\n[Output truncated. Refine the search or request a smaller line range.]'
    return `${value.slice(0, LEARN_OUTPUT_CHAR_LIMIT - suffix.length)}${suffix}`
}

function normalizeText(value: string): string {
    return value.replace(/\r\n?/g, '\n')
}

function splitLines(value: string): string[] {
    return value.split('\n')
}

function isRecord(value: unknown): value is Record<string, unknown> {
    return typeof value === 'object' && value !== null && !Array.isArray(value)
}
