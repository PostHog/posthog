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

interface SearchSnippet {
    path: string
    line: number
    text: string
}

interface RankedSkill {
    skill: SkillDefinition
    score: number
    snippets: SearchSnippet[]
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

    search(query: string): string {
        const normalizedQuery = normalizeQuery(query)
        const ranked = [...this.skillsByName.values()]
            .map((skill) => rankSkill(skill, normalizedQuery))
            .filter((result): result is RankedSkill => result !== null)
            .sort((left, right) => right.score - left.score || left.skill.name.localeCompare(right.skill.name))
            .slice(0, MAX_GLOBAL_SKILLS)

        if (ranked.length === 0) {
            return `No skills matched "${query}".`
        }

        const sections = ranked.map(({ skill, snippets }) => {
            const lines = [`## ${skill.name}`, '', skill.description]
            if (snippets.length > 0) {
                lines.push('', ...snippets.map((snippet) => `${snippet.path}:${snippet.line}: ${snippet.text}`))
            }
            return lines.join('\n')
        })
        return fitOutput(sections.join('\n\n'))
    }

    read(name: string, path?: string): string {
        const skill = this.requireSkill(name)
        if (path) {
            const file = this.requireFile(skill, path)
            return formatFile(skill, file)
        }

        const skillFile = this.requireFile(skill, 'SKILL.md')
        const manifest = formatManifest(skill)
        const full = `# ${skill.name}\n\n${skill.description}\n\n${manifest}\n\n## SKILL.md\n\n${skillFile.content}`
        if (full.length <= LEARN_OUTPUT_CHAR_LIMIT) {
            return full
        }
        return formatOversizedFile(skill, skillFile, manifest)
    }

    searchFile(name: string, path: string, query: string): string {
        const skill = this.requireSkill(name)
        const file = this.requireFile(skill, path)
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
            return `No matches for "${query}" in ${name}/${path}.`
        }

        const blocks = matchingLines.map(({ index }) => {
            const start = Math.max(0, index - SEARCH_CONTEXT_LINES)
            const end = Math.min(lines.length - 1, index + SEARCH_CONTEXT_LINES)
            return lines
                .slice(start, end + 1)
                .map((line, offset) => `${start + offset + 1}: ${line}`)
                .join('\n')
        })
        return fitOutput(`# ${name}/${path}\n\n${blocks.join('\n\n')}`)
    }

    readLines(name: string, path: string, start: number, end: number): string {
        const skill = this.requireSkill(name)
        const file = this.requireFile(skill, path)
        const lines = splitLines(file.content)
        if (!Number.isInteger(start) || !Number.isInteger(end) || start < 1 || end < start || end > lines.length) {
            throw new Error(`Invalid line range ${start}:${end}. ${name}/${path} has ${lines.length} lines.`)
        }

        const body = lines
            .slice(start - 1, end)
            .map((line, index) => `${start + index}: ${line}`)
            .join('\n')
        const result = `# ${name}/${path} lines ${start}:${end}\n\n${body}`
        if (result.length > LEARN_OUTPUT_CHAR_LIMIT) {
            throw new Error(
                `Requested line range is ${result.length} characters. Narrow it to at most ${LEARN_OUTPUT_CHAR_LIMIT} characters.`
            )
        }
        return result
    }

    private requireSkill(name: string): SkillDefinition {
        const skill = this.skillsByName.get(name)
        if (!skill) {
            throw new Error(`Unknown skill: "${name}". Use \`learn -s <query>\` to find a skill.`)
        }
        return skill
    }

    private requireFile(skill: SkillDefinition, path: string): SkillFile {
        validateRelativePath(path)
        const file = skill.files.find((candidate) => candidate.path === path)
        if (!file) {
            throw new Error(
                `Unknown file: "${path}" in skill "${skill.name}". Run \`learn ${skill.name}\` for its manifest.`
            )
        }
        return file
    }
}

function parseFrontmatter(content: string, source: string): { name: string; description: string } {
    const match = content.match(/^---\n([\s\S]*?)\n---(?:\n|$)/)
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

function makeSkillFile(path: string, content: string): SkillFile {
    const kind: SkillFileKind = path.toLowerCase().endsWith('.md')
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

function formatManifest(skill: SkillDefinition): string {
    const lines = skill.files.map((file) => `- ${file.path} (${file.lineCount} lines, ${file.charCount} chars)`)
    return `## Files\n\n${lines.join('\n')}`
}

function formatFile(skill: SkillDefinition, file: SkillFile): string {
    const header = `# ${skill.name}/${file.path}\n\n${file.lineCount} lines, ${file.charCount} chars`
    const full = `${header}\n\n${file.content}`
    if (full.length <= LEARN_OUTPUT_CHAR_LIMIT) {
        return full
    }
    return formatOversizedFile(skill, file)
}

function formatOversizedFile(skill: SkillDefinition, file: SkillFile, manifest?: string): string {
    const headings = splitLines(file.content)
        .map((line, index) => ({ line, number: index + 1 }))
        .filter(({ line }) => /^#{1,6}\s+/.test(line))
        .map(({ line, number }) => `${number}: ${line}`)
    const outline = headings.length > 0 ? headings.join('\n') : '(No Markdown headings found.)'
    const scope = manifest ? `${manifest}\n\n` : ''
    return fitOutput(
        `# ${skill.name}/${file.path}\n\n${file.lineCount} lines, ${file.charCount} chars. This file is too large to return in full. Use \`learn ${skill.name} ${file.path} -s <query>\` or \`learn ${skill.name} ${file.path} --lines <start>:<end>\`.\n\n${scope}## Heading outline\n\n${outline}`
    )
}

function rankSkill(skill: SkillDefinition, query: NormalizedQuery): RankedSkill | null {
    let score = scoreText(skill.name, query, 1_000) + scoreText(skill.description, query, 300)
    const snippets: SearchSnippet[] = []

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
    const tokens = [...new Set(phrase.match(/[a-z0-9]+/g) ?? [])]
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

function findSnippet(file: SkillFile, query: NormalizedQuery): SearchSnippet | undefined {
    const lines = splitLines(file.content)
    const index = lines.findIndex((line) => matchesQuery(line, query))
    if (index === -1) {
        return undefined
    }
    return { path: file.path, line: index + 1, text: lines[index]!.trim() }
}

function fitOutput(value: string): string {
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
