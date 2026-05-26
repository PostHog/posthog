// AUTO-GENERATED from products/batch_exports/mcp/tools.yaml + OpenAPI — do not edit
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import {
    BatchExportsCreateBody,
    BatchExportsDestroyParams,
    BatchExportsListQueryParams,
    BatchExportsPartialUpdateBody,
    BatchExportsPartialUpdateParams,
    BatchExportsRetrieveParams,
    FileDownloadBatchExportsCancelCreateBody,
    FileDownloadBatchExportsCancelCreateParams,
    FileDownloadBatchExportsCreateBody,
    FileDownloadBatchExportsRetrieveParams,
} from '@/generated/batch_exports/api'
import { withPostHogUrl, pickResponseFields, type WithPostHogUrl } from '@/tools/tool-utils'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

const BatchExportCreateSchema = BatchExportsCreateBody

const batchExportCreate = (): ToolBase<typeof BatchExportCreateSchema, Schemas.BatchExport> => ({
    name: 'batch-export-create',
    schema: BatchExportCreateSchema,
    handler: async (context: Context, params: z.infer<typeof BatchExportCreateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.name !== undefined) {
            body['name'] = params.name
        }
        if (params.model !== undefined) {
            body['model'] = params.model
        }
        if (params.destination !== undefined) {
            body['destination'] = params.destination
        }
        if (params.interval !== undefined) {
            body['interval'] = params.interval
        }
        if (params.paused !== undefined) {
            body['paused'] = params.paused
        }
        if (params.timezone !== undefined) {
            body['timezone'] = params.timezone
        }
        if (params.offset_day !== undefined) {
            body['offset_day'] = params.offset_day
        }
        if (params.offset_hour !== undefined) {
            body['offset_hour'] = params.offset_hour
        }
        const result = await context.api.request<Schemas.BatchExport>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/batch_exports/`,
            body,
        })
        return result
    },
})

const BatchExportDeleteSchema = BatchExportsDestroyParams.omit({ project_id: true })

const batchExportDelete = (): ToolBase<typeof BatchExportDeleteSchema, unknown> => ({
    name: 'batch-export-delete',
    schema: BatchExportDeleteSchema,
    handler: async (context: Context, params: z.infer<typeof BatchExportDeleteSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<unknown>({
            method: 'DELETE',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/batch_exports/${encodeURIComponent(String(params.id))}/`,
        })
        return result
    },
})

const BatchExportGetSchema = BatchExportsRetrieveParams.omit({ project_id: true })

const batchExportGet = (): ToolBase<typeof BatchExportGetSchema, Schemas.BatchExport> => ({
    name: 'batch-export-get',
    schema: BatchExportGetSchema,
    handler: async (context: Context, params: z.infer<typeof BatchExportGetSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.BatchExport>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/batch_exports/${encodeURIComponent(String(params.id))}/`,
        })
        return result
    },
})

const BatchExportUpdateSchema = BatchExportsPartialUpdateParams.omit({ project_id: true }).extend(
    BatchExportsPartialUpdateBody.shape
)

const batchExportUpdate = (): ToolBase<typeof BatchExportUpdateSchema, Schemas.BatchExport> => ({
    name: 'batch-export-update',
    schema: BatchExportUpdateSchema,
    handler: async (context: Context, params: z.infer<typeof BatchExportUpdateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.name !== undefined) {
            body['name'] = params.name
        }
        if (params.model !== undefined) {
            body['model'] = params.model
        }
        if (params.destination !== undefined) {
            body['destination'] = params.destination
        }
        if (params.interval !== undefined) {
            body['interval'] = params.interval
        }
        if (params.paused !== undefined) {
            body['paused'] = params.paused
        }
        if (params.timezone !== undefined) {
            body['timezone'] = params.timezone
        }
        if (params.offset_day !== undefined) {
            body['offset_day'] = params.offset_day
        }
        if (params.offset_hour !== undefined) {
            body['offset_hour'] = params.offset_hour
        }
        const result = await context.api.request<Schemas.BatchExport>({
            method: 'PATCH',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/batch_exports/${encodeURIComponent(String(params.id))}/`,
            body,
        })
        return result
    },
})

const BatchExportsListSchema = BatchExportsListQueryParams

const batchExportsList = (): ToolBase<
    typeof BatchExportsListSchema,
    WithPostHogUrl<Schemas.PaginatedBatchExportList>
> => ({
    name: 'batch-exports-list',
    schema: BatchExportsListSchema,
    handler: async (context: Context, params: z.infer<typeof BatchExportsListSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.PaginatedBatchExportList>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/batch_exports/`,
            query: {
                limit: params.limit,
                offset: params.offset,
            },
        })
        const filtered = {
            ...result,
            results: (result.results ?? []).map((item: any) =>
                pickResponseFields(item, [
                    'id',
                    'name',
                    'model',
                    'destination',
                    'interval',
                    'paused',
                    'created_at',
                    'last_updated_at',
                    'start_at',
                    'end_at',
                ])
            ),
        } as typeof result
        return await withPostHogUrl(context, filtered, '/data-pipelines/destinations')
    },
})

const FileDownloadBatchExportsCancelCreateSchema = FileDownloadBatchExportsCancelCreateParams.omit({
    project_id: true,
}).extend(FileDownloadBatchExportsCancelCreateBody.shape)

const fileDownloadBatchExportsCancelCreate = (): ToolBase<
    typeof FileDownloadBatchExportsCancelCreateSchema,
    unknown
> => ({
    name: 'file-download-batch-exports-cancel-create',
    schema: FileDownloadBatchExportsCancelCreateSchema,
    handler: async (context: Context, params: z.infer<typeof FileDownloadBatchExportsCancelCreateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.file !== undefined) {
            body['file'] = params.file
        }
        if (params.model !== undefined) {
            body['model'] = params.model
        }
        if (params.include !== undefined) {
            body['include'] = params.include
        }
        if (params.exclude !== undefined) {
            body['exclude'] = params.exclude
        }
        if (params.data_interval_start !== undefined) {
            body['data_interval_start'] = params.data_interval_start
        }
        if (params.data_interval_end !== undefined) {
            body['data_interval_end'] = params.data_interval_end
        }
        const result = await context.api.request<unknown>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/file_download_batch_exports/${encodeURIComponent(String(params.id))}/cancel/`,
            body,
        })
        return result
    },
})

const FileDownloadBatchExportsCreateSchema = FileDownloadBatchExportsCreateBody

const fileDownloadBatchExportsCreate = (): ToolBase<typeof FileDownloadBatchExportsCreateSchema, unknown> => ({
    name: 'file-download-batch-exports-create',
    schema: FileDownloadBatchExportsCreateSchema,
    // eslint-disable-next-line no-unused-vars
    handler: async (context: Context, params: z.infer<typeof FileDownloadBatchExportsCreateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<unknown>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/file_download_batch_exports/`,
        })
        return result
    },
})

const FileDownloadBatchExportsRetrieveSchema = FileDownloadBatchExportsRetrieveParams.omit({ project_id: true })

const fileDownloadBatchExportsRetrieve = (): ToolBase<
    typeof FileDownloadBatchExportsRetrieveSchema,
    Schemas.RetrieveFileDownloadResponse
> => ({
    name: 'file-download-batch-exports-retrieve',
    schema: FileDownloadBatchExportsRetrieveSchema,
    handler: async (context: Context, params: z.infer<typeof FileDownloadBatchExportsRetrieveSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.RetrieveFileDownloadResponse>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/file_download_batch_exports/${encodeURIComponent(String(params.id))}/`,
        })
        return result
    },
})

export const GENERATED_TOOLS: Record<string, () => ToolBase<ZodObjectAny>> = {
    'batch-export-create': batchExportCreate,
    'batch-export-delete': batchExportDelete,
    'batch-export-get': batchExportGet,
    'batch-export-update': batchExportUpdate,
    'batch-exports-list': batchExportsList,
    'file-download-batch-exports-cancel-create': fileDownloadBatchExportsCancelCreate,
    'file-download-batch-exports-create': fileDownloadBatchExportsCreate,
    'file-download-batch-exports-retrieve': fileDownloadBatchExportsRetrieve,
}
