// AUTO-GENERATED from products/agent_memory/mcp/tools.yaml + OpenAPI — do not edit
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import {
    AgentMemoryAppendCreateBody,
    AgentMemoryListQueryParams,
    AgentMemoryReadRetrieveQueryParams,
    AgentMemoryWriteCreateBody,
} from '@/generated/agent_memory/api'
import { withPostHogUrl, pickResponseFields, type WithPostHogUrl } from '@/tools/tool-utils'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

const MemoryListSchema = AgentMemoryListQueryParams

const memoryList = (): ToolBase<typeof MemoryListSchema, WithPostHogUrl<Schemas.PaginatedMemoryFileSummaryList>> => ({
    name: 'memory-list',
    schema: MemoryListSchema,
    handler: async (context: Context, params: z.infer<typeof MemoryListSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.PaginatedMemoryFileSummaryList>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/agent_memory/`,
            query: {
                limit: params.limit,
                offset: params.offset,
                prefix: params.prefix,
            },
        })
        const filtered = {
            ...result,
            results: (result.results ?? []).map((item: any) =>
                pickResponseFields(item, ['path', 'version', 'size_bytes', 'updated_by_run', 'updated_at'])
            ),
        } as typeof result
        return await withPostHogUrl(context, filtered, '/agent_memory')
    },
})

const MemoryReadSchema = AgentMemoryReadRetrieveQueryParams

const memoryRead = (): ToolBase<typeof MemoryReadSchema, Schemas.MemoryFile> => ({
    name: 'memory-read',
    schema: MemoryReadSchema,
    handler: async (context: Context, params: z.infer<typeof MemoryReadSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.MemoryFile>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/agent_memory/read/`,
            query: {
                path: params.path,
            },
        })
        return result
    },
})

const MemoryWriteSchema = AgentMemoryWriteCreateBody

const memoryWrite = (): ToolBase<typeof MemoryWriteSchema, Schemas.MemoryFile> => ({
    name: 'memory-write',
    schema: MemoryWriteSchema,
    handler: async (context: Context, params: z.infer<typeof MemoryWriteSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.path !== undefined) {
            body['path'] = params.path
        }
        if (params.content !== undefined) {
            body['content'] = params.content
        }
        if (params.expected_version !== undefined) {
            body['expected_version'] = params.expected_version
        }
        if (params.updated_by_run !== undefined) {
            body['updated_by_run'] = params.updated_by_run
        }
        const result = await context.api.request<Schemas.MemoryFile>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/agent_memory/write/`,
            body,
        })
        return result
    },
})

const MemoryAppendSchema = AgentMemoryAppendCreateBody

const memoryAppend = (): ToolBase<typeof MemoryAppendSchema, Schemas.MemoryFile> => ({
    name: 'memory-append',
    schema: MemoryAppendSchema,
    handler: async (context: Context, params: z.infer<typeof MemoryAppendSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.path !== undefined) {
            body['path'] = params.path
        }
        if (params.heading !== undefined) {
            body['heading'] = params.heading
        }
        if (params.body !== undefined) {
            body['body'] = params.body
        }
        if (params.updated_by_run !== undefined) {
            body['updated_by_run'] = params.updated_by_run
        }
        const result = await context.api.request<Schemas.MemoryFile>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/agent_memory/append/`,
            body,
        })
        return result
    },
})

export const GENERATED_TOOLS: Record<string, () => ToolBase<ZodObjectAny>> = {
    'memory-list': memoryList,
    'memory-read': memoryRead,
    'memory-write': memoryWrite,
    'memory-append': memoryAppend,
}
