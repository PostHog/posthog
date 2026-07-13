import type { ProjectSkillCatalog } from '@/skills/project-skill-catalog'
import {
    fitLearnOutput,
    formatLearnSearchResults,
    type LearnSearchResult,
    type SkillCatalog,
} from '@/skills/skill-catalog'

export interface ExecLearnGuide {
    id: string
    title: string
    description: string
    content: string
}

export type ExecLearnGuideSummary = Omit<ExecLearnGuide, 'content'>

const SKILL_COMMANDS = [
    'learn skills',
    'learn -s <query>',
    'learn posthog:<skill> [path]',
    'learn project:<skill> [path]',
    'learn <source>:<skill> <path> -s <query>',
    'learn <source>:<skill> <path> --lines <start>:<end>',
] as const
const MAX_SEARCH_QUERY_LENGTH = 200
const POSTHOG_SKILL_LIST_LIMIT = 300

type SkillSource = 'posthog' | 'project'

interface QualifiedSkill {
    source: SkillSource
    name: string
    identifier: string
}

/** Combines small bundled guides with PostHog and current-project skills. */
export class ExecLearnCatalog {
    private readonly guidesById: Map<string, ExecLearnGuide>

    constructor(
        guides: readonly ExecLearnGuide[],
        private readonly posthogSkills: SkillCatalog | undefined,
        private readonly projectSkills?: ProjectSkillCatalog,
        private readonly projectUnavailableReason?: string
    ) {
        this.guidesById = new Map()
        for (const guide of guides) {
            if (guide.id === 'skills' || guide.id.startsWith('-')) {
                throw new Error(`Reserved exec learn guide ID: "${guide.id}"`)
            }
            if (this.guidesById.has(guide.id)) {
                throw new Error(`Duplicate exec learn guide ID: "${guide.id}"`)
            }
            this.guidesById.set(guide.id, guide)
        }
    }

    async execute(input: string): Promise<string> {
        const rest = input.trim()
        if (!rest) {
            return JSON.stringify({
                guides: this.listGuides(),
                skills: {
                    posthogAvailable: this.posthogSkills !== undefined,
                    projectAvailable: this.projectSkills !== undefined,
                    commands: SKILL_COMMANDS,
                },
            })
        }

        const tokens = tokenizeLearnInput(rest)
        if (tokens.length === 1 && tokens[0] === 'skills') {
            return await this.listSkills()
        }

        if (tokens[0] === '-s') {
            const query = tokens.slice(1).join(' ')
            this.validateSearchQuery(query)
            return await this.searchSkills(query)
        }

        if (!tokens[0]!.includes(':')) {
            return this.readGuides(tokens)
        }

        const [identifier, ...args] = tokens
        const skill = parseQualifiedSkill(identifier!)
        if (args.length === 0) {
            return await this.readSkill(skill)
        }

        const [path, flag, ...flagArgs] = args
        if (!flag) {
            return await this.readSkill(skill, path)
        }
        if (flag === '-s') {
            const query = flagArgs.join(' ')
            this.validateSearchQuery(query)
            return await this.searchSkillFile(skill, path!, query)
        }
        if (flag === '--lines' && flagArgs.length === 1) {
            const range = flagArgs[0]!.match(/^(\d+):(\d+)$/)
            if (!range) {
                throw new Error('Usage: learn <source>:<skill> <path> --lines <start>:<end>')
            }
            return await this.readSkillLines(skill, path!, Number(range[1]), Number(range[2]))
        }
        throw new Error(
            'Usage: learn <source>:<skill> [path], learn <source>:<skill> <path> -s <query>, or learn <source>:<skill> <path> --lines <start>:<end>'
        )
    }

    private async listSkills(): Promise<string> {
        const allPosthogNames = this.posthogSkills?.listNames() ?? []
        const posthogNames = allPosthogNames.slice(0, POSTHOG_SKILL_LIST_LIMIT).map((name) => `posthog:${name}`)
        let project:
            | { available: true; count: number; listed: number; truncated: boolean; skills: string[] }
            | { available: false; reason: string }

        if (!this.projectSkills) {
            project = { available: false, reason: this.requireProjectUnavailableReason() }
        } else {
            try {
                const result = await this.projectSkills.listNames()
                project = {
                    available: true,
                    count: result.count,
                    listed: result.names.length,
                    truncated: result.truncated,
                    skills: result.names.map((name) => `project:${name}`),
                }
            } catch (error) {
                project = { available: false, reason: formatProjectError(error) }
            }
        }

        return fitLearnOutput(
            JSON.stringify({
                posthog: {
                    available: this.posthogSkills !== undefined,
                    count: allPosthogNames.length,
                    listed: posthogNames.length,
                    truncated: posthogNames.length < allPosthogNames.length,
                    skills: posthogNames,
                },
                project,
            })
        )
    }

    private async searchSkills(query: string): Promise<string> {
        const results: LearnSearchResult[] = this.posthogSkills?.searchResults(query, 'posthog:') ?? []
        const warnings: string[] = []
        if (!this.posthogSkills) {
            warnings.push('PostHog skills are temporarily unavailable.')
        }

        if (!this.projectSkills) {
            warnings.push(`Project skills unavailable: ${this.requireProjectUnavailableReason()}`)
        } else {
            try {
                results.push(...(await this.projectSkills.searchResults(query)))
            } catch (error) {
                warnings.push(`Project skills unavailable: ${formatProjectError(error)}`)
            }
        }

        const sections = results.length > 0 ? formatLearnSearchResults(results) : `No skills matched "${query}".`
        return fitLearnOutput(
            warnings.length > 0 ? `${sections}\n\n${warnings.map((warning) => `[${warning}]`).join('\n')}` : sections
        )
    }

    private async readSkill(skill: QualifiedSkill, path?: string): Promise<string> {
        if (skill.source === 'posthog') {
            return this.requirePostHogSkills().read(skill.name, path, skill.identifier)
        }
        return await this.requireProjectSkills().read(skill.name, path)
    }

    private async searchSkillFile(skill: QualifiedSkill, path: string, query: string): Promise<string> {
        if (skill.source === 'posthog') {
            return this.requirePostHogSkills().searchFile(skill.name, path, query, skill.identifier)
        }
        return await this.requireProjectSkills().searchFile(skill.name, path, query)
    }

    private async readSkillLines(skill: QualifiedSkill, path: string, start: number, end: number): Promise<string> {
        if (skill.source === 'posthog') {
            return this.requirePostHogSkills().readLines(skill.name, path, start, end, skill.identifier)
        }
        return await this.requireProjectSkills().readLines(skill.name, path, start, end)
    }

    private validateSearchQuery(query: string): void {
        if (!query.trim()) {
            throw new Error('Search query cannot be empty.')
        }
        if (query.length > MAX_SEARCH_QUERY_LENGTH) {
            throw new Error(`Search query must be at most ${MAX_SEARCH_QUERY_LENGTH} characters.`)
        }
    }

    private listGuides(): ExecLearnGuideSummary[] {
        return [...this.guidesById.values()].map(({ content: _content, ...summary }) => summary)
    }

    private readGuides(guideIds: string[]): string {
        const uniqueGuideIds = [...new Set(guideIds)]
        const guides = uniqueGuideIds.map((guideId) => this.guidesById.get(guideId))
        const unknownGuideIds = uniqueGuideIds.filter((_, index) => guides[index] === undefined)
        if (unknownGuideIds.length > 0) {
            const available = this.listGuides()
                .map((guide) => guide.id)
                .join(', ')
            const unknown = unknownGuideIds.map((guideId) => `"${guideId}"`).join(', ')
            throw new Error(
                `Unknown learning ${unknownGuideIds.length === 1 ? 'topic' : 'topics'}: ${unknown}. Available: ${available}`
            )
        }

        const resolvedGuides = guides.filter((guide) => guide !== undefined)
        if (resolvedGuides.length === 1) {
            return resolvedGuides[0]!.content
        }
        return resolvedGuides.map((guide) => `## ${guide.title}\n\n${guide.content}`).join('\n\n')
    }

    private requirePostHogSkills(): SkillCatalog {
        if (!this.posthogSkills) {
            throw new Error('PostHog skills are temporarily unavailable. Core exec commands are still available.')
        }
        return this.posthogSkills
    }

    private requireProjectSkills(): ProjectSkillCatalog {
        if (!this.projectSkills) {
            throw new Error(this.requireProjectUnavailableReason())
        }
        return this.projectSkills
    }

    private requireProjectUnavailableReason(): string {
        return this.projectUnavailableReason ?? 'Project skills are temporarily unavailable.'
    }
}

function parseQualifiedSkill(identifier: string): QualifiedSkill {
    const match = identifier.match(/^(posthog|project):(.+)$/)
    if (!match?.[1] || !match[2]) {
        throw new Error(
            `Unknown guide or unqualified skill: "${identifier}". Use \`learn posthog:<skill>\` or \`learn project:<skill>\`.`
        )
    }
    return { source: match[1] as SkillSource, name: match[2], identifier }
}

function tokenizeLearnInput(input: string): string[] {
    const tokens: string[] = []
    let token = ''
    let quote: '"' | "'" | undefined
    let escaping = false

    for (const character of input) {
        if (escaping) {
            token += character
            escaping = false
        } else if (character === '\\' && quote) {
            escaping = true
        } else if (quote) {
            if (character === quote) {
                quote = undefined
            } else {
                token += character
            }
        } else if (character === '"' || character === "'") {
            quote = character
        } else if (/\s/.test(character)) {
            if (token) {
                tokens.push(token)
                token = ''
            }
        } else {
            token += character
        }
    }

    if (quote) {
        throw new Error('Unterminated quote in learn command.')
    }
    if (escaping) {
        token += '\\'
    }
    if (token) {
        tokens.push(token)
    }
    return tokens
}

function formatProjectError(error: unknown): string {
    return error instanceof Error ? error.message.slice(0, 500) : 'Project skill request failed.'
}
