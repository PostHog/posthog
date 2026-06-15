// AUTO-GENERATED from products/skills/mcp/tools.yaml + OpenAPI — do not edit
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import {
    LlmSkillsCreateBody,
    LlmSkillsListQueryParams,
    LlmSkillsNameArchiveCreateParams,
    LlmSkillsNameDuplicateCreateBody,
    LlmSkillsNameDuplicateCreateParams,
    LlmSkillsNameFilesCreateBody,
    LlmSkillsNameFilesCreateParams,
    LlmSkillsNameFilesDestroyParams,
    LlmSkillsNameFilesDestroyQueryParams,
    LlmSkillsNameFilesRenameCreateBody,
    LlmSkillsNameFilesRenameCreateParams,
    LlmSkillsNameFilesRetrieveParams,
    LlmSkillsNameFilesRetrieveQueryParams,
    LlmSkillsNamePartialUpdateBody,
    LlmSkillsNamePartialUpdateParams,
    LlmSkillsNameRetrieveParams,
    LlmSkillsNameRetrieveQueryParams,
} from '@/generated/skills/api'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

const LlmaSkillArchiveSchema = LlmSkillsNameArchiveCreateParams.omit({ project_id: true }).extend({
    skill_name: LlmSkillsNameArchiveCreateParams.shape['skill_name'].describe(
        'The kebab-case name of the skill to archive.'
    ),
})

const llmaSkillArchive = (): ToolBase<typeof LlmaSkillArchiveSchema, unknown> => ({
    name: 'llma-skill-archive',
    schema: LlmaSkillArchiveSchema,
    handler: async (context: Context, params: z.infer<typeof LlmaSkillArchiveSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<unknown>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/llm_skills/name/${encodeURIComponent(String(params.skill_name))}/archive/`,
        })
        return result
    },
})

const LlmaSkillCreateSchema = LlmSkillsCreateBody

const llmaSkillCreate = (): ToolBase<typeof LlmaSkillCreateSchema, Schemas.LLMSkillCreate> => ({
    name: 'llma-skill-create',
    schema: LlmaSkillCreateSchema,
    handler: async (context: Context, params: z.infer<typeof LlmaSkillCreateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.name !== undefined) {
            body['name'] = params.name
        }
        if (params.description !== undefined) {
            body['description'] = params.description
        }
        if (params.body !== undefined) {
            body['body'] = params.body
        }
        if (params.license !== undefined) {
            body['license'] = params.license
        }
        if (params.compatibility !== undefined) {
            body['compatibility'] = params.compatibility
        }
        if (params.allowed_tools !== undefined) {
            body['allowed_tools'] = params.allowed_tools
        }
        if (params.metadata !== undefined) {
            body['metadata'] = params.metadata
        }
        if (params.files !== undefined) {
            body['files'] = params.files
        }
        const result = await context.api.request<Schemas.LLMSkillCreate>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/llm_skills/`,
            body,
        })
        return result
    },
})

const LlmaSkillDuplicateSchema = LlmSkillsNameDuplicateCreateParams.omit({ project_id: true }).extend(
    LlmSkillsNameDuplicateCreateBody.shape
)

const llmaSkillDuplicate = (): ToolBase<typeof LlmaSkillDuplicateSchema, Schemas.LLMSkill> => ({
    name: 'llma-skill-duplicate',
    schema: LlmaSkillDuplicateSchema,
    handler: async (context: Context, params: z.infer<typeof LlmaSkillDuplicateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.new_name !== undefined) {
            body['new_name'] = params.new_name
        }
        const result = await context.api.request<Schemas.LLMSkill>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/llm_skills/name/${encodeURIComponent(String(params.skill_name))}/duplicate/`,
            body,
        })
        return result
    },
})

const LlmaSkillFileCreateSchema = LlmSkillsNameFilesCreateParams.omit({ project_id: true }).extend(
    LlmSkillsNameFilesCreateBody.shape
)

const llmaSkillFileCreate = (): ToolBase<typeof LlmaSkillFileCreateSchema, Schemas.LLMSkill> => ({
    name: 'llma-skill-file-create',
    schema: LlmaSkillFileCreateSchema,
    handler: async (context: Context, params: z.infer<typeof LlmaSkillFileCreateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.path !== undefined) {
            body['path'] = params.path
        }
        if (params.content !== undefined) {
            body['content'] = params.content
        }
        if (params.content_type !== undefined) {
            body['content_type'] = params.content_type
        }
        if (params.base_version !== undefined) {
            body['base_version'] = params.base_version
        }
        const result = await context.api.request<Schemas.LLMSkill>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/llm_skills/name/${encodeURIComponent(String(params.skill_name))}/files/`,
            body,
        })
        return result
    },
})

const LlmaSkillFileDeleteSchema = LlmSkillsNameFilesDestroyParams.omit({ project_id: true }).extend(
    LlmSkillsNameFilesDestroyQueryParams.shape
)

const llmaSkillFileDelete = (): ToolBase<typeof LlmaSkillFileDeleteSchema, Schemas.LLMSkill> => ({
    name: 'llma-skill-file-delete',
    schema: LlmaSkillFileDeleteSchema,
    handler: async (context: Context, params: z.infer<typeof LlmaSkillFileDeleteSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.LLMSkill>({
            method: 'DELETE',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/llm_skills/name/${encodeURIComponent(String(params.skill_name))}/files/${encodeURIComponent(String(params.file_path))}/`,
            query: {
                base_version: params.base_version,
            },
        })
        return result
    },
})

const LlmaSkillFileGetSchema = LlmSkillsNameFilesRetrieveParams.omit({ project_id: true }).extend(
    LlmSkillsNameFilesRetrieveQueryParams.shape
)

const llmaSkillFileGet = (): ToolBase<typeof LlmaSkillFileGetSchema, Schemas.LLMSkillFile> => ({
    name: 'llma-skill-file-get',
    schema: LlmaSkillFileGetSchema,
    handler: async (context: Context, params: z.infer<typeof LlmaSkillFileGetSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.LLMSkillFile>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/llm_skills/name/${encodeURIComponent(String(params.skill_name))}/files/${encodeURIComponent(String(params.file_path))}/`,
            query: {
                version: params.version,
            },
        })
        return result
    },
})

const LlmaSkillFileRenameSchema = LlmSkillsNameFilesRenameCreateParams.omit({ project_id: true }).extend(
    LlmSkillsNameFilesRenameCreateBody.shape
)

const llmaSkillFileRename = (): ToolBase<typeof LlmaSkillFileRenameSchema, Schemas.LLMSkill> => ({
    name: 'llma-skill-file-rename',
    schema: LlmaSkillFileRenameSchema,
    handler: async (context: Context, params: z.infer<typeof LlmaSkillFileRenameSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.old_path !== undefined) {
            body['old_path'] = params.old_path
        }
        if (params.new_path !== undefined) {
            body['new_path'] = params.new_path
        }
        if (params.base_version !== undefined) {
            body['base_version'] = params.base_version
        }
        const result = await context.api.request<Schemas.LLMSkill>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/llm_skills/name/${encodeURIComponent(String(params.skill_name))}/files-rename/`,
            body,
        })
        return result
    },
})

const LlmaSkillGetSchema = LlmSkillsNameRetrieveParams.omit({ project_id: true }).extend(
    LlmSkillsNameRetrieveQueryParams.shape
)

const llmaSkillGet = (): ToolBase<typeof LlmaSkillGetSchema, Schemas.LLMSkill> => ({
    name: 'llma-skill-get',
    schema: LlmaSkillGetSchema,
    handler: async (context: Context, params: z.infer<typeof LlmaSkillGetSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.LLMSkill>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/llm_skills/name/${encodeURIComponent(String(params.skill_name))}/`,
            query: {
                version: params.version,
            },
        })
        return result
    },
})

const LlmaSkillListSchema = LlmSkillsListQueryParams

const llmaSkillList = (): ToolBase<typeof LlmaSkillListSchema, Schemas.PaginatedLLMSkillListList> => ({
    name: 'llma-skill-list',
    schema: LlmaSkillListSchema,
    handler: async (context: Context, params: z.infer<typeof LlmaSkillListSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.PaginatedLLMSkillListList>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/llm_skills/`,
            query: {
                created_by_id: params.created_by_id,
                limit: params.limit,
                offset: params.offset,
                search: params.search,
            },
        })
        return result
    },
})

const LlmaSkillUpdateSchema = LlmSkillsNamePartialUpdateParams.omit({ project_id: true }).extend(
    LlmSkillsNamePartialUpdateBody.shape
)

const llmaSkillUpdate = (): ToolBase<typeof LlmaSkillUpdateSchema, Schemas.LLMSkill> => ({
    name: 'llma-skill-update',
    schema: LlmaSkillUpdateSchema,
    handler: async (context: Context, params: z.infer<typeof LlmaSkillUpdateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.body !== undefined) {
            body['body'] = params.body
        }
        if (params.edits !== undefined) {
            body['edits'] = params.edits
        }
        if (params.description !== undefined) {
            body['description'] = params.description
        }
        if (params.license !== undefined) {
            body['license'] = params.license
        }
        if (params.compatibility !== undefined) {
            body['compatibility'] = params.compatibility
        }
        if (params.allowed_tools !== undefined) {
            body['allowed_tools'] = params.allowed_tools
        }
        if (params.metadata !== undefined) {
            body['metadata'] = params.metadata
        }
        if (params.files !== undefined) {
            body['files'] = params.files
        }
        if (params.file_edits !== undefined) {
            body['file_edits'] = params.file_edits
        }
        if (params.base_version !== undefined) {
            body['base_version'] = params.base_version
        }
        const result = await context.api.request<Schemas.LLMSkill>({
            method: 'PATCH',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/llm_skills/name/${encodeURIComponent(String(params.skill_name))}/`,
            body,
        })
        return result
    },
})

export const GENERATED_TOOLS: Record<string, () => ToolBase<ZodObjectAny>> = {
    'llma-skill-archive': llmaSkillArchive,
    'llma-skill-create': llmaSkillCreate,
    'llma-skill-duplicate': llmaSkillDuplicate,
    'llma-skill-file-create': llmaSkillFileCreate,
    'llma-skill-file-delete': llmaSkillFileDelete,
    'llma-skill-file-get': llmaSkillFileGet,
    'llma-skill-file-rename': llmaSkillFileRename,
    'llma-skill-get': llmaSkillGet,
    'llma-skill-list': llmaSkillList,
    'llma-skill-update': llmaSkillUpdate,
}
