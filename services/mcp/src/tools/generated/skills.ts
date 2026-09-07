// AUTO-GENERATED from products/skills/mcp/tools.yaml + OpenAPI — do not edit
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import * as orvalSchemas from '@/generated/skills/api'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

const SkillArchiveSchema = () => {
    const LlmSkillsNameArchiveCreateParams = orvalSchemas.LlmSkillsNameArchiveCreateParams()
    return LlmSkillsNameArchiveCreateParams.omit({ project_id: true }).extend({
        skill_name: LlmSkillsNameArchiveCreateParams.shape['skill_name'].describe(
            'The kebab-case name of the skill to archive.'
        ),
    })
}

const skillArchive = (): ToolBase<ReturnType<typeof SkillArchiveSchema>, unknown> => ({
    name: 'skill-archive',
    schema: SkillArchiveSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof SkillArchiveSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<unknown>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/llm_skills/name/${encodeURIComponent(String(params.skill_name))}/archive/`,
        })
        return result
    },
})

const SkillCreateSchema = () => {
    const LlmSkillsCreateBody = orvalSchemas.LlmSkillsCreateBody()
    return LlmSkillsCreateBody
}

const skillCreate = (): ToolBase<ReturnType<typeof SkillCreateSchema>, Schemas.LLMSkill> => ({
    name: 'skill-create',
    schema: SkillCreateSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof SkillCreateSchema>>) => {
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
        if (params.owners !== undefined) {
            body['owners'] = params.owners
        }
        if (params.files !== undefined) {
            body['files'] = params.files
        }
        const result = await context.api.request<Schemas.LLMSkill>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/llm_skills/`,
            body,
        })
        return result
    },
})

const SkillDuplicateSchema = () => {
    const LlmSkillsNameDuplicateCreateBody = orvalSchemas.LlmSkillsNameDuplicateCreateBody()
    const LlmSkillsNameDuplicateCreateParams = orvalSchemas.LlmSkillsNameDuplicateCreateParams()
    return LlmSkillsNameDuplicateCreateParams.omit({ project_id: true }).extend(LlmSkillsNameDuplicateCreateBody.shape)
}

const skillDuplicate = (): ToolBase<ReturnType<typeof SkillDuplicateSchema>, Schemas.LLMSkill> => ({
    name: 'skill-duplicate',
    schema: SkillDuplicateSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof SkillDuplicateSchema>>) => {
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

const SkillFileCreateSchema = () => {
    const LlmSkillsNameFilesCreateBody = orvalSchemas.LlmSkillsNameFilesCreateBody()
    const LlmSkillsNameFilesCreateParams = orvalSchemas.LlmSkillsNameFilesCreateParams()
    return LlmSkillsNameFilesCreateParams.omit({ project_id: true }).extend(LlmSkillsNameFilesCreateBody.shape)
}

const skillFileCreate = (): ToolBase<ReturnType<typeof SkillFileCreateSchema>, Schemas.LLMSkill> => ({
    name: 'skill-file-create',
    schema: SkillFileCreateSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof SkillFileCreateSchema>>) => {
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

const SkillFileDeleteSchema = () => {
    const LlmSkillsNameFilesDestroyParams = orvalSchemas.LlmSkillsNameFilesDestroyParams()
    const LlmSkillsNameFilesDestroyQueryParams = orvalSchemas.LlmSkillsNameFilesDestroyQueryParams()
    return LlmSkillsNameFilesDestroyParams.omit({ project_id: true }).extend(LlmSkillsNameFilesDestroyQueryParams.shape)
}

const skillFileDelete = (): ToolBase<ReturnType<typeof SkillFileDeleteSchema>, Schemas.LLMSkill> => ({
    name: 'skill-file-delete',
    schema: SkillFileDeleteSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof SkillFileDeleteSchema>>) => {
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

const SkillFileGetSchema = () => {
    const LlmSkillsNameFilesRetrieveParams = orvalSchemas.LlmSkillsNameFilesRetrieveParams()
    const LlmSkillsNameFilesRetrieveQueryParams = orvalSchemas.LlmSkillsNameFilesRetrieveQueryParams()
    return LlmSkillsNameFilesRetrieveParams.omit({ project_id: true }).extend(
        LlmSkillsNameFilesRetrieveQueryParams.shape
    )
}

const skillFileGet = (): ToolBase<ReturnType<typeof SkillFileGetSchema>, Schemas.LLMSkillFile> => ({
    name: 'skill-file-get',
    schema: SkillFileGetSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof SkillFileGetSchema>>) => {
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

const SkillFileRenameSchema = () => {
    const LlmSkillsNameFilesRenameCreateBody = orvalSchemas.LlmSkillsNameFilesRenameCreateBody()
    const LlmSkillsNameFilesRenameCreateParams = orvalSchemas.LlmSkillsNameFilesRenameCreateParams()
    return LlmSkillsNameFilesRenameCreateParams.omit({ project_id: true }).extend(
        LlmSkillsNameFilesRenameCreateBody.shape
    )
}

const skillFileRename = (): ToolBase<ReturnType<typeof SkillFileRenameSchema>, Schemas.LLMSkill> => ({
    name: 'skill-file-rename',
    schema: SkillFileRenameSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof SkillFileRenameSchema>>) => {
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

const SkillGetSchema = () => {
    const LlmSkillsNameRetrieveParams = orvalSchemas.LlmSkillsNameRetrieveParams()
    const LlmSkillsNameRetrieveQueryParams = orvalSchemas.LlmSkillsNameRetrieveQueryParams()
    return LlmSkillsNameRetrieveParams.omit({ project_id: true }).extend(LlmSkillsNameRetrieveQueryParams.shape)
}

const skillGet = (): ToolBase<ReturnType<typeof SkillGetSchema>, Schemas.LLMSkill> => ({
    name: 'skill-get',
    schema: SkillGetSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof SkillGetSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.LLMSkill>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/llm_skills/name/${encodeURIComponent(String(params.skill_name))}/`,
            query: {
                body_length: params.body_length,
                body_offset: params.body_offset,
                version: params.version,
            },
        })
        return result
    },
})

const SkillListSchema = () => {
    const LlmSkillsListQueryParams = orvalSchemas.LlmSkillsListQueryParams()
    return LlmSkillsListQueryParams
}

const skillList = (): ToolBase<ReturnType<typeof SkillListSchema>, Schemas.PaginatedLLMSkillListList> => ({
    name: 'skill-list',
    schema: SkillListSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof SkillListSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.PaginatedLLMSkillListList>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/llm_skills/`,
            query: {
                category: params.category,
                created_by_id: params.created_by_id,
                limit: params.limit,
                offset: params.offset,
                owner_id: params.owner_id,
                search: params.search,
            },
        })
        return result
    },
})

const SkillStoreInstallCommandSchema = () => {
    const LlmSkillsMarketplaceInstallCommandCreateBody = orvalSchemas.LlmSkillsMarketplaceInstallCommandCreateBody()
    return LlmSkillsMarketplaceInstallCommandCreateBody.extend({
        rotate: LlmSkillsMarketplaceInstallCommandCreateBody.shape['rotate'].describe(
            "Set true only when the user explicitly wants a fresh token (e.g. setting up a new machine): it rolls the caller's existing credential, invalidating their previous token. Leave false (default) to reuse the existing credential — the first call always mints one regardless."
        ),
    })
}

const skillStoreInstallCommand = (): ToolBase<
    ReturnType<typeof SkillStoreInstallCommandSchema>,
    Schemas.LLMSkillMarketplaceCommand
> => ({
    name: 'skill-store-install-command',
    schema: SkillStoreInstallCommandSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof SkillStoreInstallCommandSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.rotate !== undefined) {
            body['rotate'] = params.rotate
        }
        const result = await context.api.request<Schemas.LLMSkillMarketplaceCommand>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/llm_skills/marketplace/install-command/`,
            body,
        })
        return result
    },
})

const SkillUpdateSchema = () => {
    const LlmSkillsNamePartialUpdateBody = orvalSchemas.LlmSkillsNamePartialUpdateBody()
    const LlmSkillsNamePartialUpdateParams = orvalSchemas.LlmSkillsNamePartialUpdateParams()
    return LlmSkillsNamePartialUpdateParams.omit({ project_id: true }).extend(LlmSkillsNamePartialUpdateBody.shape)
}

const skillUpdate = (): ToolBase<ReturnType<typeof SkillUpdateSchema>, Schemas.LLMSkill> => ({
    name: 'skill-update',
    schema: SkillUpdateSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof SkillUpdateSchema>>) => {
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
        if (params.owners !== undefined) {
            body['owners'] = params.owners
        }
        if (params.base_version !== undefined) {
            body['base_version'] = params.base_version
        }
        if (params.version_description !== undefined) {
            body['version_description'] = params.version_description
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
    'skill-archive': skillArchive,
    'skill-create': skillCreate,
    'skill-duplicate': skillDuplicate,
    'skill-file-create': skillFileCreate,
    'skill-file-delete': skillFileDelete,
    'skill-file-get': skillFileGet,
    'skill-file-rename': skillFileRename,
    'skill-get': skillGet,
    'skill-list': skillList,
    'skill-store-install-command': skillStoreInstallCommand,
    'skill-update': skillUpdate,
}
