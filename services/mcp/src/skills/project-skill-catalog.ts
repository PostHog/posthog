import type { Schemas } from '@/api/generated'
import {
    extractQueryTokens,
    formatLearnDocument,
    formatLearnFile,
    type LearnSearchResult,
    type LearnSearchSnippet,
    makeSkillFile,
    MIN_STEM_VARIANT_LENGTH,
    readLearnLines,
    scoreProjectSearchResult,
    searchLearnFile,
    type SkillFile,
} from '@/skills/skill-catalog'
import type { Context } from '@/tools/types'

const PROJECT_SKILL_LIST_PAGE_SIZE = 100
const PROJECT_SKILL_LIST_LIMIT = 200
// Zero-hit fallback fan-out: at most this many single-token backend searches, longest tokens first.
const MAX_FALLBACK_SEARCH_TOKENS = 3

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
        const results = response.results.map((skill) =>
            this.toSearchResult(query, skill.name, skill.description, skill.matches)
        )
        if (results.length > 0) {
            return results
        }
        // The backend icontains-matches the WHOLE query, so a natural multi-word query returns
        // nothing even when a skill's body or bundled files match individual words — which would
        // bias the cross-source merge against project skills, since PostHog skills are searched
        // locally over full content. Recover cheapest-first: bounded per-token backend searches
        // (these do reach body/file content), then a purely local rank of the memoized listing.
        const tokenResults = await this.searchByTokens(query)
        if (tokenResults.length > 0) {
            return tokenResults
        }
        return await this.rankListing(query)
    }

    /**
     * Whole-query backend search yielded nothing: retry with a few informative single tokens so
     * body/file-content matches surface. Each token search runs independently — a failing one must
     * not sink the fallback — and hits are merged by skill name, then scored against the ORIGINAL
     * full query so cross-source merge ordering stays consistent.
     */
    private async searchByTokens(query: string): Promise<LearnSearchResult[]> {
        const tokens = informativeSearchTokens(query)
        if (tokens.length === 0) {
            return []
        }
        const responses = await Promise.allSettled(tokens.map((token) => this.search(token)))
        const merged = new Map<string, { description: string; matches: Schemas.LLMSkillSearchMatch[] }>()
        for (const outcome of responses) {
            if (outcome.status !== 'fulfilled') {
                continue
            }
            for (const skill of outcome.value.results) {
                const existing = merged.get(skill.name)
                if (existing) {
                    existing.matches.push(...skill.matches)
                } else {
                    merged.set(skill.name, { description: skill.description, matches: [...skill.matches] })
                }
            }
        }
        return [...merged.entries()].map(([name, { description, matches }]) =>
            this.toSearchResult(query, name, description, matches)
        )
    }

    /** Last-resort local rank of the memoized listing (name + description only) when even per-token search finds nothing. */
    private async rankListing(query: string): Promise<LearnSearchResult[]> {
        const { skills } = await this.list()
        return skills
            .map((skill) => ({
                identifier: `project:${skill.name}`,
                description: skill.description,
                snippets: [] as LearnSearchSnippet[],
                score: scoreProjectSearchResult(query, skill.name, skill.description, []),
            }))
            .filter((result) => result.score > 0)
    }

    private toSearchResult(
        query: string,
        name: string,
        description: string,
        matches: readonly Schemas.LLMSkillSearchMatch[]
    ): LearnSearchResult {
        return {
            identifier: `project:${name}`,
            description,
            snippets: dedupeSnippets(
                matches.map((match) => ({
                    path: match.path ?? match.matched_field,
                    line: match.line ?? 1,
                    text: match.excerpt,
                }))
            ),
            // Scored client-side so project and PostHog results merge into one relevance order.
            score: scoreProjectSearchResult(
                query,
                name,
                description,
                matches.map((match) => match.matched_field)
            ),
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

/**
 * Informative single tokens for the zero-hit per-token fallback: the scorer's own tokenization,
 * dropping tokens too short to be selective, longest first (more specific), capped for fan-out.
 */
function informativeSearchTokens(query: string): string[] {
    return extractQueryTokens(query)
        .filter((token) => token.length >= MIN_STEM_VARIANT_LENGTH)
        .sort((left, right) => right.length - left.length)
        .slice(0, MAX_FALLBACK_SEARCH_TOKENS)
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
