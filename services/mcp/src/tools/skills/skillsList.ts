import type { z } from 'zod'

import { SkillsListSchema } from '@/schema/tool-inputs'
import type { Context, ToolBase } from '@/tools/types'

import { fetchSkillsIndex, type SkillIndexEntry } from './registryClient'

const schema = SkillsListSchema

type Params = z.infer<typeof schema>

// Drop large fields (source_path, sha256) and per-archive URL from the list
// response — those are only needed when fetching a single skill.
type ListedSkill = Omit<SkillIndexEntry, 'source_path' | 'sha256' | 'archive_url'>

type Result = {
    index_version: string
    generated_at: string
    total: number
    skills: ListedSkill[]
}

export const skillsListHandler: ToolBase<typeof schema, Result>['handler'] = async (
    _context: Context,
    params: Params
) => {
    const index = await fetchSkillsIndex()

    const needle = params.search?.toLowerCase()
    const tagSet = params.tags?.length ? new Set(params.tags) : undefined
    const productSet = params.products?.length ? new Set(params.products) : undefined

    const filtered = index.skills.filter((skill) => {
        if (params.category && skill.category !== params.category) {
            return false
        }
        if (params.source && skill.source !== params.source) {
            return false
        }
        if (tagSet && !skill.tags.some((t) => tagSet.has(t))) {
            return false
        }
        if (productSet && !skill.products.some((p) => productSet.has(p))) {
            return false
        }
        if (needle) {
            const haystack = `${skill.name}\n${skill.description}`.toLowerCase()
            if (!haystack.includes(needle)) {
                return false
            }
        }
        return true
    })

    const listed: ListedSkill[] = filtered.map(({ source_path: _sp, sha256: _sha, archive_url: _url, ...rest }) => rest)

    return {
        index_version: index.version,
        generated_at: index.generated_at,
        total: listed.length,
        skills: listed,
    }
}

const tool = (): ToolBase<typeof schema, Result> => ({
    name: 'skills-list',
    schema,
    handler: skillsListHandler,
})

export default tool
