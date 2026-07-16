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

/** Request-scoped access to the current project's Skills store. */
export class ProjectSkillCatalog {
    constructor(private readonly context: Context) {}

    async listNames(): Promise<ProjectSkillList> {
        const projectId = await this.context.stateManager.getProjectId()
        const names: string[] = []
        let count = 0

        while (names.length < PROJECT_SKILL_LIST_LIMIT) {
            const response = await this.context.api.request<Schemas.PaginatedLLMSkillListList>({
                method: 'GET',
                path: `/api/projects/${encodeURIComponent(String(projectId))}/llm_skills/`,
                query: {
                    category: '',
                    limit: Math.min(PROJECT_SKILL_LIST_PAGE_SIZE, PROJECT_SKILL_LIST_LIMIT - names.length),
                    offset: names.length,
                    order_by: 'name',
                },
            })
            count = response.count
            names.push(...response.results.map((skill) => skill.name))
            if (response.results.length === 0 || names.length >= response.count) {
                break
            }
        }

        return { count, names, truncated: names.length < count }
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

    private async getSkill(name: string): Promise<Schemas.LLMSkill> {
        const projectId = await this.context.stateManager.getProjectId()
        return await this.context.api.request<Schemas.LLMSkill>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/llm_skills/name/${encodeURIComponent(name)}/`,
        })
    }

    private async getFile(name: string, path: string): Promise<SkillFile> {
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
    }
}
