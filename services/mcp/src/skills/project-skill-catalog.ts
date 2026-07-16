import type { Schemas } from '@/api/generated'
import {
    formatLearnDocument,
    formatLearnFile,
    type LearnSearchResult,
    makeSkillFile,
    readLearnLines,
    searchLearnFile,
    type SkillFile,
} from '@/skills/skill-catalog'
import type { Context } from '@/tools/types'

const PROJECT_SKILL_LIST_PAGE_SIZE = 100
const PROJECT_SKILL_LIST_LIMIT = 200

export interface ProjectSkillList {
    count: number
    names: string[]
    truncated: boolean
}

interface ProjectSkillListing {
    count: number
    skills: Array<{ name: string; description: string }>
    truncated: boolean
}

/**
 * Request-scoped access to the current project's Skills store.
 *
 * The instance lives for a single MCP request, so every fetch is memoized with no
 * invalidation: repeated reads and concurrent batch calls within one request dedupe to a
 * single API round-trip. Promises (not resolved values) are cached so in-flight concurrent
 * calls share one request; a rejected promise is evicted so a transient error doesn't poison
 * the rest of the request.
 */
export class ProjectSkillCatalog {
    private readonly skillMemo = new Map<string, Promise<Schemas.LLMSkill>>()
    private readonly fileMemo = new Map<string, Promise<SkillFile>>()
    private listMemo?: Promise<ProjectSkillListing>

    constructor(private readonly context: Context) {}

    async listNames(): Promise<ProjectSkillList> {
        const { count, skills, truncated } = await this.list()
        return { count, names: skills.map((skill) => skill.name), truncated }
    }

    /** name → description for the project's skills, sourced from the same list endpoint as `listNames`. */
    async descriptions(): Promise<Map<string, string>> {
        const { skills } = await this.list()
        return new Map(skills.map((skill) => [skill.name, skill.description]))
    }

    async searchResults(query: string): Promise<LearnSearchResult[]> {
        const projectId = await this.context.stateManager.getProjectId()
        const response = await this.context.api.request<Schemas.LLMSkillSearchResponse>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/llm_skills/search/`,
            query: { query },
        })

        return response.results.map((skill) => ({
            identifier: `project:${skill.name}`,
            description: skill.description,
            snippets: skill.matches.map((match) => ({
                path: match.path ?? match.matched_field,
                line: match.line ?? 1,
                text: match.excerpt,
            })),
        }))
    }

    async read(name: string, path?: string): Promise<string> {
        const identifier = `project:${name}`
        if (path) {
            const file = await this.getFile(name, path)
            return formatLearnFile(identifier, file)
        }

        const skill = await this.getSkill(name)
        const skillFile = makeSkillFile('SKILL.md', skill.body, 'text/markdown')
        return formatLearnDocument(identifier, skill.description, skillFile, [
            skillFile,
            ...skill.files.map((file) => ({
                path: file.path,
                lineCount: file.line_count,
                charCount: file.char_count,
            })),
        ])
    }

    async searchFile(name: string, path: string, query: string): Promise<string> {
        return searchLearnFile(`project:${name}`, await this.getFile(name, path), query)
    }

    async readLines(name: string, path: string, start: number, end: number): Promise<string> {
        return readLearnLines(`project:${name}`, await this.getFile(name, path), start, end)
    }

    private getSkill(name: string): Promise<Schemas.LLMSkill> {
        return this.memoize(this.skillMemo, name, async () => {
            const projectId = await this.context.stateManager.getProjectId()
            return await this.context.api.request<Schemas.LLMSkill>({
                method: 'GET',
                path: `/api/projects/${encodeURIComponent(String(projectId))}/llm_skills/name/${encodeURIComponent(name)}/`,
            })
        })
    }

    private getFile(name: string, path: string): Promise<SkillFile> {
        // Name can't contain a space (validated lowercase-alphanumeric-hyphen), so it's a safe separator from the free-form path.
        return this.memoize(this.fileMemo, `${name} ${path}`, async () => {
            if (path === 'SKILL.md') {
                const skill = await this.getSkill(name)
                return makeSkillFile('SKILL.md', skill.body, 'text/markdown')
            }
            const projectId = await this.context.stateManager.getProjectId()
            const file = await this.context.api.request<Schemas.LLMSkillFile>({
                method: 'GET',
                path: `/api/projects/${encodeURIComponent(String(projectId))}/llm_skills/name/${encodeURIComponent(name)}/files/${encodeURIComponent(path)}/`,
            })
            return makeSkillFile(file.path, file.content, file.content_type)
        })
    }

    /** Shared pagination for `listNames`/`descriptions` — memoized so a request never pages the list endpoint twice. */
    private list(): Promise<ProjectSkillListing> {
        if (!this.listMemo) {
            this.listMemo = this.fetchList().catch((error) => {
                this.listMemo = undefined
                throw error
            })
        }
        return this.listMemo
    }

    private async fetchList(): Promise<ProjectSkillListing> {
        const projectId = await this.context.stateManager.getProjectId()
        const skills: Array<{ name: string; description: string }> = []
        let count = 0

        while (skills.length < PROJECT_SKILL_LIST_LIMIT) {
            const response = await this.context.api.request<Schemas.PaginatedLLMSkillListList>({
                method: 'GET',
                path: `/api/projects/${encodeURIComponent(String(projectId))}/llm_skills/`,
                query: {
                    category: '',
                    limit: Math.min(PROJECT_SKILL_LIST_PAGE_SIZE, PROJECT_SKILL_LIST_LIMIT - skills.length),
                    offset: skills.length,
                    order_by: 'name',
                },
            })
            count = response.count
            skills.push(...response.results.map((skill) => ({ name: skill.name, description: skill.description })))
            if (response.results.length === 0 || skills.length >= response.count) {
                break
            }
        }

        return { count, skills, truncated: skills.length < count }
    }

    private memoize<T>(cache: Map<string, Promise<T>>, key: string, factory: () => Promise<T>): Promise<T> {
        const existing = cache.get(key)
        if (existing) {
            return existing
        }
        const promise = factory().catch((error) => {
            // Evict on rejection so a transient API error doesn't poison later reads in the same request.
            cache.delete(key)
            throw error
        })
        cache.set(key, promise)
        return promise
    }
}
