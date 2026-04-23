// AUTO-GENERATED from products/llm_analytics/mcp/skills.yaml + OpenAPI — do not edit
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import {
    LlmSkillsCreateBody,
    LlmSkillsListQueryParams,
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

const SkillCreateSchema = LlmSkillsCreateBody

const skillCreate = (): ToolBase<typeof SkillCreateSchema, Schemas.LLMSkillCreate> => ({
    name: 'skill-create',
    schema: SkillCreateSchema,
    handler: async (context: Context, params: z.infer<typeof SkillCreateSchema>) => {
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
            path: `/api/environments/${encodeURIComponent(String(projectId))}/llm_skills/`,
            body,
        })
        return result
    },
})

const SkillDuplicateSchema = LlmSkillsNameDuplicateCreateParams.omit({ project_id: true }).extend(
    LlmSkillsNameDuplicateCreateBody.shape
)

const skillDuplicate = (): ToolBase<typeof SkillDuplicateSchema, Schemas.LLMSkill> => ({
    name: 'skill-duplicate',
    schema: SkillDuplicateSchema,
    handler: async (context: Context, params: z.infer<typeof SkillDuplicateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.new_name !== undefined) {
            body['new_name'] = params.new_name
        }
        const result = await context.api.request<Schemas.LLMSkill>({
            method: 'POST',
            path: `/api/environments/${encodeURIComponent(String(projectId))}/llm_skills/name/${encodeURIComponent(String(params.skill_name))}/duplicate/`,
            body,
        })
        return result
    },
})

const SkillFileCreateSchema = LlmSkillsNameFilesCreateParams.omit({ project_id: true }).extend(
    LlmSkillsNameFilesCreateBody.shape
)

const skillFileCreate = (): ToolBase<typeof SkillFileCreateSchema, Schemas.LLMSkill> => ({
    name: 'skill-file-create',
    schema: SkillFileCreateSchema,
    handler: async (context: Context, params: z.infer<typeof SkillFileCreateSchema>) => {
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
            path: `/api/environments/${encodeURIComponent(String(projectId))}/llm_skills/name/${encodeURIComponent(String(params.skill_name))}/files/`,
            body,
        })
        return result
    },
})

const SkillFileDeleteSchema = LlmSkillsNameFilesDestroyParams.omit({ project_id: true }).extend(
    LlmSkillsNameFilesDestroyQueryParams.shape
)

const skillFileDelete = (): ToolBase<typeof SkillFileDeleteSchema, Schemas.LLMSkill> => ({
    name: 'skill-file-delete',
    schema: SkillFileDeleteSchema,
    handler: async (context: Context, params: z.infer<typeof SkillFileDeleteSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.LLMSkill>({
            method: 'DELETE',
            path: `/api/environments/${encodeURIComponent(String(projectId))}/llm_skills/name/${encodeURIComponent(String(params.skill_name))}/files/${encodeURIComponent(String(params.file_path))}/`,
            query: {
                base_version: params.base_version,
            },
        })
        return result
    },
})

const SkillFileGetSchema = LlmSkillsNameFilesRetrieveParams.omit({ project_id: true }).extend(
    LlmSkillsNameFilesRetrieveQueryParams.shape
)

const skillFileGet = (): ToolBase<typeof SkillFileGetSchema, Schemas.LLMSkillFile> => ({
    name: 'skill-file-get',
    schema: SkillFileGetSchema,
    handler: async (context: Context, params: z.infer<typeof SkillFileGetSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.LLMSkillFile>({
            method: 'GET',
            path: `/api/environments/${encodeURIComponent(String(projectId))}/llm_skills/name/${encodeURIComponent(String(params.skill_name))}/files/${encodeURIComponent(String(params.file_path))}/`,
            query: {
                version: params.version,
            },
        })
        return result
    },
})

const SkillFileRenameSchema = LlmSkillsNameFilesRenameCreateParams.omit({ project_id: true }).extend(
    LlmSkillsNameFilesRenameCreateBody.shape
)

const skillFileRename = (): ToolBase<typeof SkillFileRenameSchema, Schemas.LLMSkill> => ({
    name: 'skill-file-rename',
    schema: SkillFileRenameSchema,
    handler: async (context: Context, params: z.infer<typeof SkillFileRenameSchema>) => {
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
            path: `/api/environments/${encodeURIComponent(String(projectId))}/llm_skills/name/${encodeURIComponent(String(params.skill_name))}/files-rename/`,
            body,
        })
        return result
    },
})

const SkillGetSchema = LlmSkillsNameRetrieveParams.omit({ project_id: true }).extend(
    LlmSkillsNameRetrieveQueryParams.shape
)

const skillGet = (): ToolBase<typeof SkillGetSchema, Schemas.LLMSkill> => ({
    name: 'skill-get',
    schema: SkillGetSchema,
    handler: async (context: Context, params: z.infer<typeof SkillGetSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.LLMSkill>({
            method: 'GET',
            path: `/api/environments/${encodeURIComponent(String(projectId))}/llm_skills/name/${encodeURIComponent(String(params.skill_name))}/`,
            query: {
                version: params.version,
            },
        })
        return result
    },
})

const SkillListSchema = LlmSkillsListQueryParams

const skillList = (): ToolBase<typeof SkillListSchema, Schemas.PaginatedLLMSkillListList> => ({
    name: 'skill-list',
    schema: SkillListSchema,
    handler: async (context: Context, params: z.infer<typeof SkillListSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.PaginatedLLMSkillListList>({
            method: 'GET',
            path: `/api/environments/${encodeURIComponent(String(projectId))}/llm_skills/`,
            query: {
                limit: params.limit,
                offset: params.offset,
                search: params.search,
            },
        })
        return result
    },
})

const SkillUpdateSchema = LlmSkillsNamePartialUpdateParams.omit({ project_id: true }).extend(
    LlmSkillsNamePartialUpdateBody.shape
)

const skillUpdate = (): ToolBase<typeof SkillUpdateSchema, Schemas.LLMSkill> => ({
    name: 'skill-update',
    schema: SkillUpdateSchema,
    handler: async (context: Context, params: z.infer<typeof SkillUpdateSchema>) => {
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
            path: `/api/environments/${encodeURIComponent(String(projectId))}/llm_skills/name/${encodeURIComponent(String(params.skill_name))}/`,
            body,
        })
        return result
    },
})

export const GENERATED_TOOLS: Record<string, () => ToolBase<ZodObjectAny>> = {
    'skill-create': skillCreate,
    'skill-duplicate': skillDuplicate,
    'skill-file-create': skillFileCreate,
    'skill-file-delete': skillFileDelete,
    'skill-file-get': skillFileGet,
    'skill-file-rename': skillFileRename,
    'skill-get': skillGet,
    'skill-list': skillList,
    'skill-update': skillUpdate,
}
