import type { Schemas } from '@/api/generated'
import {
    formatLearnDocument,
    formatLearnFile,
    type LearnSearchResult,
    type LearnSearchSnippet,
    makeSkillFile,
    readLearnLines,
    searchLearnFile,
    type SkillFile,
} from '@/skills/skill-catalog'
import type { Context } from '@/tools/types'

const PROJECT_SKILL_LIST_PAGE_SIZE = 100
const PROJECT_SKILL_LIST_LIMIT = 200
// Matches MAX_SKILL_BODY_BYTES in products/skills/backend/api/skill_serializers.py.
const MAX_PROJECT_SKILL_BODY_BYTES = 1_000_000

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

    /**
     * name → description for the requested skills. Seeds from the memoized listing; for names the
     * listing missed only because it was capped (`truncated`), resolves each via the uncapped
     * exact-name endpoint so a real skill past the cap isn't misreported as unknown. When the
     * listing is complete, a miss is authoritative and no extra fetch is made. Fan-out is bounded
     * by the caller (at most `MAX_DESCRIBE_SKILLS` names).
     */
    async describe(names: string[]): Promise<Map<string, string>> {
        const listing = await this.list()
        const descriptions = new Map(listing.skills.map((skill) => [skill.name, skill.description]))
        if (!listing.truncated) {
            return descriptions
        }
        const missing = [...new Set(names)].filter((name) => !descriptions.has(name))
        if (missing.length === 0) {
            return descriptions
        }
        const fetched = await Promise.allSettled(missing.map((name) => this.getSkill(name)))
        missing.forEach((name, index) => {
            const outcome = fetched[index]!
            if (outcome.status === 'fulfilled') {
                descriptions.set(name, outcome.value.description)
            }
            // Rejected: a 404 is an authoritative "no such skill"; any other transient error also
            // degrades to the same `[unknown skill]` rendering. Both omit — the exact-name read
            // path still resolves a real skill, so a described-as-unknown result stays recoverable.
        })
        return descriptions
    }

    async searchResults(query: string): Promise<LearnSearchResult[]> {
        const response = await this.search(query)
        return response.results.map((skill) =>
            this.toSearchResult(skill.name, skill.description, skill.score, skill.matches)
        )
    }

    private toSearchResult(
        name: string,
        description: string,
        score: number,
        matches: readonly Schemas.LLMSkillSearchMatch[]
    ): LearnSearchResult {
        return {
            identifier: `project:${name}`,
            description,
            // Name and description matches carry no path; the header already prints both.
            snippets: dedupeSnippets(
                matches
                    .filter(
                        (match): match is Schemas.LLMSkillSearchMatch & { path: string } => match.path !== undefined
                    )
                    .map((match) => ({
                        path: match.path,
                        line: match.line ?? 1,
                        text: match.excerpt,
                    }))
            ),
            score,
        }
    }

    private async search(query: string): Promise<Schemas.LLMSkillSearchResponse> {
        const projectId = await this.context.stateManager.getProjectId()
        return await this.context.api.request<Schemas.LLMSkillSearchResponse>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/llm_skills/search/`,
            query: { query },
        })
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
            const path = `/api/projects/${encodeURIComponent(String(projectId))}/llm_skills/name/${encodeURIComponent(name)}/`
            const skill = await this.context.api.request<Schemas.LLMSkill>({
                method: 'GET',
                path,
                // A character count this large covers every valid UTF-8 body without the API's default paging.
                query: { body_length: MAX_PROJECT_SKILL_BODY_BYTES },
            })
            if (new TextEncoder().encode(skill.body).byteLength > MAX_PROJECT_SKILL_BODY_BYTES) {
                throw new Error('Skill body exceeds the 1 MB limit. Split detailed instructions into companion files.')
            }

            // Django counts Unicode code points; JavaScript string.length counts UTF-16 code units.
            let bodyLength = 0
            for (const _character of skill.body) {
                bodyLength++
            }
            if (skill.body_next_offset !== null || bodyLength !== skill.body_total_length) {
                throw new Error('The API returned an incomplete skill body. Try fetching the skill again.')
            }
            return skill
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

function dedupeSnippets(snippets: LearnSearchSnippet[]): LearnSearchSnippet[] {
    const seen = new Set<string>()
    const unique: LearnSearchSnippet[] = []
    for (const snippet of snippets) {
        const key = `${snippet.path}:${snippet.line}`
        if (!seen.has(key)) {
            seen.add(key)
            unique.push(snippet)
        }
    }
    return unique
}
