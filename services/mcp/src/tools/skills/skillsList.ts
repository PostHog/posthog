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

    const filtered = needle
        ? index.skills.filter((skill) => {
              const haystack = `${skill.name}\n${skill.description}`.toLowerCase()
              return haystack.includes(needle)
          })
        : index.skills

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
