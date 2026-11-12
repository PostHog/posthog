import { strFromU8, type UnzipFileInfo, type Unzipped, unzipSync } from 'fflate'
import { parse as parseYaml } from 'yaml'

export const PRODUCT_SKILL_ARCHIVE_URL =
    'https://github.com/PostHog/posthog/releases/download/agent-skills-latest/skills.zip'

export const LEARN_OUTPUT_CHAR_LIMIT = 44_000

// Also the cap applied after merging PostHog and project results in `learn -s`.
export const MAX_GLOBAL_SKILLS = 10
const MAX_GLOBAL_SNIPPETS = 2
const MAX_SCOPED_MATCHES = 50
const SEARCH_CONTEXT_LINES = 2
const MAX_ARCHIVE_FILES = 5_000
const MAX_ARCHIVE_FILE_BYTES = 8 * 1024 * 1024
const MAX_ARCHIVE_UNCOMPRESSED_BYTES = 64 * 1024 * 1024
/** The largest skills release a download accepts, before it is unzipped. */
export const MAX_SKILL_ARCHIVE_BYTES = 32 * 1024 * 1024
const EXACT_NAME_SCORE_BONUS = 5_000
// context-mill's omnibus skills ship docs snapshots and example apps as references, and
// snippet matches in those would crowd the workflow skills out of the result limit. Search
// scores them by name, description and SKILL.md only; reads by path stay open.
const ENTRY_POINT_ONLY_SKILL_PREFIX = 'instrument-'

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
    // Populated by `SkillCatalog.searchResults`; optional so client-scored project
    // results (which merge in via a separate path) can omit it until they are scored.
    score?: number
}

interface RankedSkill {
    skill: SkillDefinition
    score: number
    snippets: LearnSearchSnippet[]
}

export class LearnLookupError extends Error {
    constructor(
        readonly code: 'unknown_skill' | 'unknown_file' | 'unknown_topic',
        message: string
    ) {
        super(message)
        this.name = 'LearnLookupError'
    }
}

/**
 * Runtime view of the published product skill bundle. The bundle is parsed
 * once per refresh; all learn operations use this in-memory representation.
 */
/**
 * The commands that the text around a skill tells the reader to run. The MCP `learn` command takes a file as
 * the word after the skill. A CLI with its own commands passes them instead.
 */
export interface LearnCommands {
    /** Reads a skill, one file in it, or a line range of that file. */
    read(identifier: string, path?: string, lines?: string): string
    /** Finds skills by keywords. */
    search(query: string): string
    /** Searches one file. Without it, a file too large to show points to a line range only. */
    searchFile?(identifier: string, path: string, query: string): string
    /** Follows "Read a file with ..." in a skill's file list, such as how to separate the words. */
    fileNote?: string
}

export function learnCommands(command = 'learn'): LearnCommands {
    return {
        read: (identifier, path, lines) =>
            `${command} ${identifier}${path === undefined ? '' : ` ${path}`}${lines === undefined ? '' : ` --lines ${lines}`}`,
        search: (query) => `${command} -s ${query}`,
        searchFile: (identifier, path, query) => `${command} ${identifier} ${path} -s ${query}`,
        fileNote: 'Separate the skill name and path with a space; do not use --file.',
    }
}

const LINE_RANGE = '<start>:<end>'

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

    static fromZip(bytes: Uint8Array, overlayBytes?: Uint8Array): SkillCatalog {
        const catalog = SkillCatalog.fromFiles(unzipUntrusted(bytes, 'Skill archive'))
        return overlayBytes ? catalog.withOverlay(SkillCatalog.fromZip(overlayBytes)) : catalog
    }

    static fromFiles(files: Unzipped): SkillCatalog {
        return new SkillCatalog(parseSkillFiles(files))
    }

    withOverlay(overlay: SkillCatalog): SkillCatalog {
        const skillsByName = new Map(this.skillsByName)

        for (const [name, skill] of overlay.skillsByName) {
            if (skillsByName.has(name)) {
                // The product archive can be sha-pinned and the overlay is not, so the overlay never replaces a product skill.
                console.warn(`[SkillCatalog] overlay skill "${name}" ignored: a product skill has that name`)
                continue
            }
            skillsByName.set(name, skill)
        }

        return new SkillCatalog([...skillsByName.values()])
    }

    mapText(rewrite: (text: string) => string): SkillCatalog {
        return new SkillCatalog(
            [...this.skillsByName.values()].map((skill) => ({
                name: skill.name,
                description: rewrite(skill.description),
                files: skill.files.map((file) => makeSkillFile(file.path, rewrite(file.content))),
            }))
        )
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

    describe(name: string): string | undefined {
        return this.skillsByName.get(name)?.description
    }

    get(name: string): SkillDefinition | undefined {
        return this.skillsByName.get(name)
    }

    searchResults(query: string, namespace = ''): LearnSearchResult[] {
        const normalizedQuery = normalizeQuery(query)
        return [...this.skillsByName.values()]
            .map((skill) => rankSkill(skill, normalizedQuery))
            .filter((result): result is RankedSkill => result !== null)
            .sort((left, right) => right.score - left.score || left.skill.name.localeCompare(right.skill.name))
            .slice(0, MAX_GLOBAL_SKILLS)
            .map(({ skill, snippets, score }) => ({
                identifier: `${namespace}${skill.name}`,
                description: skill.description,
                snippets,
                score,
            }))
    }

    search(query: string, namespace = ''): string {
        const results = this.searchResults(query, namespace)

        if (results.length === 0) {
            return `No skills matched "${query}".`
        }
        return formatLearnSearchResults(results)
    }

    read(name: string, path?: string, identifier = name, commands = learnCommands()): string {
        const skill = this.requireSkill(name, commands)

        if (path) {
            const file = this.requireFile(skill, path, identifier, commands)
            return formatLearnFile(identifier, file, commands)
        }

        const skillFile = this.requireFile(skill, 'SKILL.md', identifier, commands)
        return formatLearnDocument(identifier, skill.description, skillFile, skill.files, commands)
    }

    searchFile(name: string, path: string, query: string, identifier = name, commands = learnCommands()): string {
        const skill = this.requireSkill(name, commands)
        const file = this.requireFile(skill, path, identifier, commands)
        return searchLearnFile(identifier, file, query, commands)
    }

    readLines(
        name: string,
        path: string,
        start: number,
        end: number,
        identifier = name,
        commands = learnCommands()
    ): string {
        const skill = this.requireSkill(name, commands)
        const file = this.requireFile(skill, path, identifier, commands)
        return readLearnLines(identifier, file, start, end)
    }

    private requireSkill(name: string, commands: LearnCommands): SkillDefinition {
        const skill = this.skillsByName.get(name)

        if (!skill) {
            throw new LearnLookupError(
                'unknown_skill',
                `Unknown skill: "${name}". Use \`${commands.search('<query>')}\` to find a skill.`
            )
        }

        return skill
    }

    private requireFile(skill: SkillDefinition, path: string, identifier: string, commands: LearnCommands): SkillFile {
        validateRelativePath(path)
        const file = skill.files.find((candidate) => candidate.path === path)

        if (!file) {
            throw new LearnLookupError(
                'unknown_file',
                `Unknown file: "${path}" in skill "${identifier}". Run \`${commands.read(identifier)}\` for its manifest.`
            )
        }

        return file
    }
}

const FRONTMATTER_PATTERN = /^---\n([\s\S]*?)\n---(?:\n|$)/

export function parseFrontmatter(content: string, source: string): { name: string; description: string } {
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

function isSafeRelativePath(path: string): boolean {
    return (
        !!path &&
        !path.startsWith('/') &&
        !path.includes('\\') &&
        !path.includes('\0') &&
        path.split('/').every((part) => part && part !== '.' && part !== '..')
    )
}

function validateRelativePath(path: string): void {
    if (!isSafeRelativePath(path)) {
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
        lineCount: countLines(content),
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
    manifestFiles: readonly SkillManifestEntry[],
    commands = learnCommands()
): string {
    const note = commands.fileNote === undefined ? '' : ` ${commands.fileNote}`
    const manifest = `${formatManifest(manifestFiles)}\nRead a file with \`${commands.read(identifier, '<path>')}\`.${note}`
    const full = `Skill: ${identifier}\nDescription: ${description}\n\n${manifest}\n\nSKILL.md content (frontmatter omitted):\n\n${stripFrontmatter(skillFile.content)}`
    if (full.length <= LEARN_OUTPUT_CHAR_LIMIT) {
        return full
    }
    return formatOversizedFile(identifier, skillFile, commands, manifest)
}

export function formatLearnFile(identifier: string, file: SkillFile, commands = learnCommands()): string {
    const header = `File: ${identifier}/${file.path} (${file.lineCount} lines, ${file.charCount} chars)`
    const full = `${header}\n\n${file.content}`
    if (full.length <= LEARN_OUTPUT_CHAR_LIMIT) {
        return full
    }
    return formatOversizedFile(identifier, file, commands)
}

function formatOversizedFile(identifier: string, file: SkillFile, commands: LearnCommands, manifest?: string): string {
    const scope = manifest ? `${manifest}\n\n` : ''
    const lines = commands.read(identifier, file.path, LINE_RANGE)
    const next = commands.searchFile
        ? `Use \`${commands.searchFile(identifier, file.path, '<query>')}\` or \`${lines}\`.`
        : `Read part of it with \`${lines}\`, using the line numbers in the heading outline.`
    let output = appendLearnOutput(
        '',
        `File: ${identifier}/${file.path} (${file.lineCount} lines, ${file.charCount} chars)\nThis file is too large to return in full. ${next}\n\n${scope}Heading outline:\n`
    )
    let hasHeadings = false
    for (const line of scanLines(file.content)) {
        if (output.length > LEARN_OUTPUT_CHAR_LIMIT) {
            break
        }
        const text = file.content.slice(line.start, line.end)
        if (/^#{1,6}\s+/.test(text)) {
            output = appendLearnOutput(output, `${hasHeadings ? '\n' : ''}${line.number}: `)
            output = appendLearnOutput(output, text)
            hasHeadings = true
        }
    }
    return fitLearnOutput(hasHeadings ? output : appendLearnOutput(output, '(No Markdown headings found.)'))
}

export function searchLearnFile(
    identifier: string,
    file: SkillFile,
    query: string,
    commands = learnCommands()
): string {
    if (file.kind !== 'markdown') {
        throw new Error('Only Markdown contents are searchable. Read the file directly or use --lines instead.')
    }

    const normalizedQuery = normalizeQuery(query)
    let output = appendLearnOutput('', `Matches in ${identifier}/${file.path}:\n\n`)
    let matches = 0
    const previousStarts: number[] = []
    for (const line of scanLines(file.content)) {
        if (matchesQuery(file.content.slice(line.start, line.end), normalizedQuery)) {
            if (matches > 0) {
                output = appendLearnOutput(output, '\n\n')
            }
            const startNumber = line.number - previousStarts.length
            for (const context of scanLines(file.content, previousStarts[0] ?? line.start, startNumber)) {
                output = appendLearnOutput(output, `${context.number === startNumber ? '' : '\n'}${context.number}: `)
                output = appendLearnOutput(output, file.content.slice(context.start, context.end))
                if (context.number === line.number + SEARCH_CONTEXT_LINES || output.length > LEARN_OUTPUT_CHAR_LIMIT) {
                    break
                }
            }
            matches += 1
            if (matches === MAX_SCOPED_MATCHES || output.length > LEARN_OUTPUT_CHAR_LIMIT) {
                break
            }
        }
        previousStarts.push(line.start)
        if (previousStarts.length > SEARCH_CONTEXT_LINES) {
            previousStarts.shift()
        }
    }

    if (matches === 0) {
        return (
            `No matches for "${query}" in ${identifier}/${file.path}.\n` +
            `Read it with \`${commands.read(identifier, file.path)}\` (${file.lineCount} lines, ${file.charCount} chars) or \`${commands.read(identifier, file.path, LINE_RANGE)}\`.`
        )
    }

    return fitLearnOutput(output)
}

export function readLearnLines(identifier: string, file: SkillFile, start: number, end: number): string {
    if (!Number.isInteger(start) || !Number.isInteger(end) || start < 1 || end < start || end > file.lineCount) {
        throw new Error(`Invalid line range ${start}:${end}. ${identifier}/${file.path} has ${file.lineCount} lines.`)
    }

    let result = `File: ${identifier}/${file.path} lines ${start}:${end}\n\n`
    for (const line of scanLines(file.content)) {
        if (line.number < start) {
            continue
        }
        result = appendLearnOutput(result, `${line.number === start ? '' : '\n'}${line.number}: `)
        result = appendLearnOutput(result, file.content.slice(line.start, line.end))
        if (result.length > LEARN_OUTPUT_CHAR_LIMIT) {
            throw new Error(
                `Requested line range exceeds ${LEARN_OUTPUT_CHAR_LIMIT} characters. Request a smaller line range.`
            )
        }
        if (line.number === end) {
            break
        }
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

export interface ExtractionBudget {
    files: number
    bytes: number
}

// Checks each file before it is inflated, so a crafted archive fails before it allocates. Only the
// files `filter` keeps count against the limits.
export function unzipUntrusted(
    bytes: Uint8Array,
    label: string,
    filter: (file: UnzipFileInfo) => boolean = () => true,
    budget: ExtractionBudget = { files: 0, bytes: 0 }
): Unzipped {
    return unzipSync(bytes, {
        filter: (file) => {
            if (file.name.endsWith('/') || !filter(file)) {
                return false
            }

            if (!isSafeRelativePath(file.name)) {
                throw new Error(`${label} has an unsafe path: "${file.name}"`)
            }

            budget.files += 1
            budget.bytes += file.originalSize

            if (
                budget.files > MAX_ARCHIVE_FILES ||
                file.originalSize > MAX_ARCHIVE_FILE_BYTES ||
                budget.bytes > MAX_ARCHIVE_UNCOMPRESSED_BYTES
            ) {
                throw new Error(`${label} exceeds the extraction limit`)
            }

            return true
        },
    })
}

function parseSkillFiles(archive: Unzipped): SkillDefinition[] {
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
    return skills
}

function rankSkill(skill: SkillDefinition, query: NormalizedQuery): RankedSkill | null {
    let score =
        (skill.name.toLowerCase() === query.phrase ? EXACT_NAME_SCORE_BONUS : 0) +
        scoreText(skill.name, query, 1_000) +
        scoreText(skill.description, query, 300)
    let filePathScore = 0
    let fileContentScore = 0
    const snippetCandidates: { score: number; snippet: LearnSearchSnippet }[] = []

    for (const file of skill.files) {
        const isSkillFile = file.path === 'SKILL.md'
        if (!isSkillFile && skill.name.startsWith(ENTRY_POINT_ONLY_SKILL_PREFIX)) {
            continue
        }
        if (!isSkillFile) {
            filePathScore = Math.max(filePathScore, scoreText(file.path, query, 120))
        }
        if (file.kind !== 'markdown') {
            continue
        }
        // Exclude the YAML frontmatter from SKILL.md scoring and snippets: the
        // description already scores via `skill.description` (avoid double-counting)
        // and its snippet would just repeat the description line already printed.
        const frontmatterLines = isSkillFile ? frontmatterLineSpan(file.content) : 0
        const contentWeight = isSkillFile ? 80 : 40
        const scoredContent =
            frontmatterLines > 0 ? splitLines(file.content).slice(frontmatterLines).join('\n') : file.content
        const contentScore = scoreText(scoredContent, query, contentWeight)
        if (isSkillFile) {
            score += contentScore
        } else {
            fileContentScore = Math.max(fileContentScore, contentScore)
        }
        const snippet = findSnippet(file, query, frontmatterLines)
        if (snippet) {
            snippetCandidates.push({ score: contentScore, snippet })
        }
    }

    score += filePathScore + fileContentScore
    const snippets = snippetCandidates
        .sort((left, right) => right.score - left.score || left.snippet.path.localeCompare(right.snippet.path))
        .slice(0, MAX_GLOBAL_SNIPPETS)
        .map(({ snippet }) => snippet)

    return score > 0 ? { skill, score, snippets } : null
}

interface QueryToken {
    // A token matches text if the text includes ANY variant. Variants add light
    // stemming so related word forms still match.
    variants: string[]
}

interface NormalizedQuery {
    phrase: string
    tokens: QueryToken[]
}

const DERIVATIONAL_STEM_SUFFIXES = ['ations', 'ation', 'tions', 'tion', 'ings', 'ing', 'ed']
const SIBILANT_ES_ENDINGS = ['ches', 'shes', 'sses', 'xes', 'zes']
const MAX_SEARCH_TOKENS = 8
const MIN_SEARCH_TOKEN_LENGTH = 2
// Shortest token length the scorer treats as informative — also the floor for derived stems.
export const MIN_STEM_VARIANT_LENGTH = 5

/**
 * Bounded, deduped, lower-cased query tokens using the same tokenization the scorer applies,
 * exported so callers derive tokens identically instead of inventing a divergent tokenizer.
 */
export function extractQueryTokens(query: string): string[] {
    const rawTokens = [
        ...new Set(
            query
                .trim()
                .toLowerCase()
                .match(/[\p{L}\p{N}]+/gu) ?? []
        ),
    ]
    const informativeTokens = rawTokens.filter((token) => token.length >= MIN_SEARCH_TOKEN_LENGTH)
    return (informativeTokens.length > 0 ? informativeTokens : rawTokens.slice(0, 1))
        .map((token, index) => ({ index, token }))
        .sort((left, right) => right.token.length - left.token.length || left.index - right.index)
        .slice(0, MAX_SEARCH_TOKENS)
        .map(({ token }) => token)
}

function normalizeQuery(query: string): NormalizedQuery {
    const phrase = query.trim().toLowerCase()
    if (!phrase) {
        throw new Error('Search query cannot be empty.')
    }
    const rawTokens = extractQueryTokens(query)
    if (rawTokens.length === 0) {
        throw new Error('Search query must contain a letter or number.')
    }
    return { phrase, tokens: rawTokens.map((token) => ({ variants: stemVariants(token) })) }
}

// Only ASCII-alpha tokens of 6+ chars are stemmed; the min-5 guard on derived stems
// prevents over-matching (e.g. "sessions" must not reach "assessing" via a 4-char "sess").
function stemVariants(token: string): string[] {
    if (token.length < 6 || !/^[a-z]+$/.test(token)) {
        return [token]
    }
    const stems: string[] = []
    const suffix = DERIVATIONAL_STEM_SUFFIXES.find(
        (candidate) => token.length > candidate.length && token.endsWith(candidate)
    )
    if (suffix) {
        stems.push(token.slice(0, -suffix.length))
    } else if (token.endsWith('ies')) {
        stems.push(`${token.slice(0, -3)}y`)
    } else if (SIBILANT_ES_ENDINGS.some((ending) => token.endsWith(ending))) {
        stems.push(token.slice(0, -2))
    } else if (token.endsWith('es')) {
        stems.push(token.slice(0, -1), token.slice(0, -2))
    } else if (token.endsWith('s') && token !== 'status' && !token.endsWith('is') && !token.endsWith('ss')) {
        stems.push(token.slice(0, -1))
    } else {
        return [token]
    }

    const variants = [token]
    for (const stem of stems) {
        variants.push(stem)
        if (stem.length >= 2 && stem.at(-1) === stem.at(-2)) {
            variants.push(stem.slice(0, -1))
        }
    }
    return [...new Set(variants.filter((variant) => variant.length >= MIN_STEM_VARIANT_LENGTH))]
}

function tokenMatches(token: QueryToken, normalizedText: string): boolean {
    return token.variants.some((variant) => normalizedText.includes(variant))
}

function scoreText(text: string, query: NormalizedQuery, weight: number): number {
    const normalizedText = text.toLowerCase()
    let score = normalizedText.includes(query.phrase) ? weight * 2 : 0
    const matchingTokens = query.tokens.filter((token) => tokenMatches(token, normalizedText)).length
    if (matchingTokens === query.tokens.length) {
        score += weight
    } else {
        score += matchingTokens * Math.max(1, Math.floor(weight / query.tokens.length / 4))
    }
    return score
}

function matchesQuery(text: string, query: NormalizedQuery): boolean {
    const normalizedText = text.toLowerCase()
    return normalizedText.includes(query.phrase) || query.tokens.every((token) => tokenMatches(token, normalizedText))
}

// `skipLines` drops leading frontmatter lines while preserving raw line numbers, so the
// emitted `path:line` still matches what `--lines`/file reads return.
function findSnippet(file: SkillFile, query: NormalizedQuery, skipLines = 0): LearnSearchSnippet | undefined {
    const lines = splitLines(file.content)
    for (let index = skipLines; index < lines.length; index += 1) {
        if (matchesQuery(lines[index]!, query)) {
            return { path: file.path, line: index + 1, text: lines[index]!.trim() }
        }
    }
    return undefined
}

// Number of leading lines occupied by the YAML frontmatter block (0 when absent).
function frontmatterLineSpan(content: string): number {
    const match = FRONTMATTER_PATTERN.exec(content)
    return match ? (match[0].match(/\n/g)?.length ?? 0) : 0
}

export function fitLearnOutput(value: string): string {
    if (value.length <= LEARN_OUTPUT_CHAR_LIMIT) {
        return value
    }
    const suffix = '\n\n[Output truncated. Refine the search or request a smaller line range.]'
    return `${value.slice(0, LEARN_OUTPUT_CHAR_LIMIT - suffix.length)}${suffix}`
}

// Keep one extra character so fitLearnOutput can distinguish exact fits from truncated output.
function appendLearnOutput(output: string, value: string): string {
    return output + value.slice(0, Math.max(0, LEARN_OUTPUT_CHAR_LIMIT + 1 - output.length))
}

function countLines(content: string): number {
    let count = 1
    for (let index = content.indexOf('\n'); index !== -1; index = content.indexOf('\n', index + 1)) {
        count += 1
    }
    return count
}

function* scanLines(content: string, start = 0, number = 1): Generator<{ start: number; end: number; number: number }> {
    for (;;) {
        const newline = content.indexOf('\n', start)
        yield { start, end: newline === -1 ? content.length : newline, number }
        if (newline === -1) {
            return
        }
        start = newline + 1
        number += 1
    }
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
