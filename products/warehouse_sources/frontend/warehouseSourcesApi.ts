import { ApiConfig, ApiMethodOptions, PaginatedResponse } from 'lib/api'

import { ExternalDataSourceType, SourceConfig } from '~/queries/schema/schema-general'
import {
    ExternalDataJob,
    ExternalDataSchemaWithSource,
    ExternalDataSource,
    ExternalDataSourceCreatePayload,
    ExternalDataSourceRevenueAnalyticsConfig,
    ExternalDataSourceSchema,
    ExternalDataSourceSyncSchema,
    SchemaIncrementalFieldsResponse,
    WebhookInfo,
} from '~/types'

import {
    externalDataSchemasCancelCreate,
    externalDataSchemasDeleteDataDestroy,
    externalDataSchemasIncrementalFieldsCreate,
    externalDataSchemasPartialUpdate,
    externalDataSchemasReloadCreate,
    externalDataSchemasResyncCreate,
    externalDataSchemasRetrieve,
    externalDataSourcesBulkUpdateSchemasPartialUpdate,
    externalDataSourcesCdcStatusRetrieve,
    externalDataSourcesCheckCdcPrerequisitesCreate,
    externalDataSourcesCheckCdcPrerequisitesForSourceCreate,
    externalDataSourcesCreate,
    externalDataSourcesCreateWebhookCreate,
    externalDataSourcesDatabaseSchemaCreate,
    externalDataSourcesDeleteWebhookCreate,
    externalDataSourcesDestroy,
    externalDataSourcesDisableCdcCreate,
    externalDataSourcesEnableCdcCreate,
    externalDataSourcesJobsList,
    externalDataSourcesList,
    externalDataSourcesPartialUpdate,
    externalDataSourcesRefreshSchemasCreate,
    externalDataSourcesReloadCreate,
    externalDataSourcesRetrieve,
    externalDataSourcesRevenueAnalyticsConfigPartialUpdate,
    externalDataSourcesSourcePrefixCreate,
    externalDataSourcesUpdateCdcSettingsCreate,
    externalDataSourcesUpdateWebhookInputsCreate,
    externalDataSourcesWebhookInfoRetrieve,
    externalDataSourcesWizardRetrieve,
} from './generated/api'

// nosemgrep: prefer-codegen-api
const projectId = (): string => String(ApiConfig.getCurrentProjectId())
const requestOptions = (options?: ApiMethodOptions): RequestInit | undefined =>
    options ? { headers: options.headers, signal: options.signal } : undefined
const emptySourcePayload = (): Parameters<typeof externalDataSourcesReloadCreate>[2] =>
    ({}) as Parameters<typeof externalDataSourcesReloadCreate>[2]

interface CdcStatus {
    enabled: boolean
    management_mode?: 'posthog' | 'self_managed'
    slot_name?: string
    publication_name?: string
    lag_warning_threshold_mb?: number
    lag_critical_threshold_mb?: number
    slot_exists?: boolean
    publication_exists?: boolean
    lag_bytes?: number | null
    published_tables?: string[]
    schedule_paused?: boolean
}

export const externalDataSourcesApi = {
    async list(options?: ApiMethodOptions): Promise<PaginatedResponse<ExternalDataSource>> {
        return (await externalDataSourcesList(
            projectId(),
            undefined,
            requestOptions(options)
        )) as unknown as PaginatedResponse<ExternalDataSource>
    },
    async get(sourceId: string): Promise<ExternalDataSource> {
        return (await externalDataSourcesRetrieve(projectId(), sourceId)) as unknown as ExternalDataSource
    },
    async create(data: Partial<ExternalDataSourceCreatePayload>): Promise<{ id: string }> {
        return (await externalDataSourcesCreate(
            projectId(),
            data as Parameters<typeof externalDataSourcesCreate>[1]
        )) as { id: string }
    },
    async delete(sourceId: string): Promise<void> {
        await externalDataSourcesDestroy(projectId(), sourceId)
    },
    async reload(sourceId: string): Promise<void> {
        await externalDataSourcesReloadCreate(projectId(), sourceId, emptySourcePayload())
    },
    async getWebhookInfo(sourceId: string): Promise<WebhookInfo> {
        return (await externalDataSourcesWebhookInfoRetrieve(projectId(), sourceId)) as unknown as WebhookInfo
    },
    async createWebhook(
        sourceId: string
    ): Promise<{ success: boolean; webhook_url: string; error?: string; pending_inputs?: string[] }> {
        return (await externalDataSourcesCreateWebhookCreate(
            projectId(),
            sourceId,
            emptySourcePayload()
        )) as unknown as {
            success: boolean
            webhook_url: string
            error?: string
            pending_inputs?: string[]
        }
    },
    async updateWebhookInputs(sourceId: string, inputs: Record<string, unknown>): Promise<{ success: boolean }> {
        return (await externalDataSourcesUpdateWebhookInputsCreate(projectId(), sourceId, {
            inputs,
        } as unknown as Parameters<typeof externalDataSourcesUpdateWebhookInputsCreate>[2])) as unknown as {
            success: boolean
        }
    },
    async deleteWebhook(
        sourceId: string
    ): Promise<{ success: boolean; external_deleted: boolean; error?: string | null }> {
        return (await externalDataSourcesDeleteWebhookCreate(
            projectId(),
            sourceId,
            emptySourcePayload()
        )) as unknown as {
            success: boolean
            external_deleted: boolean
            error?: string | null
        }
    },
    async refreshSchemas(
        sourceId: string
    ): Promise<{ added: number; deleted: number; auto_enabled: number; total_tables_seen: number }> {
        return (await externalDataSourcesRefreshSchemasCreate(
            projectId(),
            sourceId,
            emptySourcePayload()
        )) as unknown as {
            added: number
            deleted: number
            auto_enabled: number
            total_tables_seen: number
        }
    },
    async bulkUpdateSchemas(
        sourceId: string,
        schemas: (Partial<ExternalDataSourceSchema> &
            Pick<ExternalDataSourceSchema, 'id'> & { apply_sync_defaults?: boolean })[]
    ): Promise<ExternalDataSourceSchema[]> {
        const response = await externalDataSourcesBulkUpdateSchemasPartialUpdate(projectId(), sourceId, {
            schemas,
        } as unknown as Parameters<typeof externalDataSourcesBulkUpdateSchemasPartialUpdate>[2])
        return response as unknown as ExternalDataSourceSchema[]
    },
    async update(sourceId: string, data: Partial<ExternalDataSource>): Promise<ExternalDataSource> {
        return (await externalDataSourcesPartialUpdate(
            projectId(),
            sourceId,
            data as Parameters<typeof externalDataSourcesPartialUpdate>[2]
        )) as unknown as ExternalDataSource
    },
    async database_schema(
        sourceType: ExternalDataSourceType,
        payload: Record<string, unknown>
    ): Promise<ExternalDataSourceSyncSchema[]> {
        return (await externalDataSourcesDatabaseSchemaCreate(projectId(), {
            source_type: sourceType,
            ...payload,
        } as Parameters<
            typeof externalDataSourcesDatabaseSchemaCreate
        >[1])) as unknown as ExternalDataSourceSyncSchema[]
    },
    async wizard(): Promise<Record<string, SourceConfig>> {
        return (await externalDataSourcesWizardRetrieve(projectId())) as unknown as Record<string, SourceConfig>
    },
    async source_prefix(sourceType: ExternalDataSourceType, prefix: string): Promise<ExternalDataSourceSyncSchema[]> {
        return (await externalDataSourcesSourcePrefixCreate(projectId(), {
            source_type: sourceType,
            prefix,
        } as unknown as Parameters<
            typeof externalDataSourcesSourcePrefixCreate
        >[1])) as unknown as ExternalDataSourceSyncSchema[]
    },
    async check_cdc_prerequisites(
        payload: Record<string, unknown>,
        teamId?: number
    ): Promise<{ valid: boolean; errors: string[] }> {
        return (await externalDataSourcesCheckCdcPrerequisitesCreate(
            String(teamId ?? projectId()),
            payload as unknown as Parameters<typeof externalDataSourcesCheckCdcPrerequisitesCreate>[1]
        )) as { valid: boolean; errors: string[] }
    },
    async check_cdc_prerequisites_for_source(
        sourceId: string,
        payload: Record<string, unknown>
    ): Promise<{ valid: boolean; errors: string[] }> {
        return (await externalDataSourcesCheckCdcPrerequisitesForSourceCreate(
            projectId(),
            sourceId,
            payload as unknown as Parameters<typeof externalDataSourcesCheckCdcPrerequisitesForSourceCreate>[2]
        )) as unknown as { valid: boolean; errors: string[] }
    },
    async enable_cdc(sourceId: string, payload: Record<string, unknown>): Promise<{ success: boolean }> {
        return (await externalDataSourcesEnableCdcCreate(
            projectId(),
            sourceId,
            payload as Parameters<typeof externalDataSourcesEnableCdcCreate>[2]
        )) as unknown as { success: boolean }
    },
    async disable_cdc(sourceId: string): Promise<{ success: boolean }> {
        return (await externalDataSourcesDisableCdcCreate(projectId(), sourceId, emptySourcePayload())) as unknown as {
            success: boolean
        }
    },
    async cdc_status(sourceId: string): Promise<CdcStatus> {
        return (await externalDataSourcesCdcStatusRetrieve(projectId(), sourceId)) as unknown as CdcStatus
    },
    async update_cdc_settings(sourceId: string, payload: Record<string, unknown>): Promise<{ success: boolean }> {
        return (await externalDataSourcesUpdateCdcSettingsCreate(
            projectId(),
            sourceId,
            payload as Parameters<typeof externalDataSourcesUpdateCdcSettingsCreate>[2]
        )) as unknown as { success: boolean }
    },
    async jobs(
        sourceId: string,
        before: string | null,
        after: string | null,
        schemas?: string[]
    ): Promise<ExternalDataJob[]> {
        return (await externalDataSourcesJobsList(projectId(), sourceId, {
            before: before ?? undefined,
            after: after ?? undefined,
            schemas,
        })) as unknown as ExternalDataJob[]
    },
    async updateRevenueAnalyticsConfig(
        sourceId: string,
        data: Partial<ExternalDataSourceRevenueAnalyticsConfig>
    ): Promise<ExternalDataSource> {
        return (await externalDataSourcesRevenueAnalyticsConfigPartialUpdate(
            projectId(),
            sourceId,
            data as Parameters<typeof externalDataSourcesRevenueAnalyticsConfigPartialUpdate>[2]
        )) as unknown as ExternalDataSource
    },
}

export const externalDataSchemasApi = {
    async get(schemaId: string): Promise<ExternalDataSchemaWithSource> {
        return (await externalDataSchemasRetrieve(projectId(), schemaId)) as unknown as ExternalDataSchemaWithSource
    },
    async update(schemaId: string, data: Partial<ExternalDataSourceSchema>): Promise<ExternalDataSourceSchema> {
        return (await externalDataSchemasPartialUpdate(
            projectId(),
            schemaId,
            data as Parameters<typeof externalDataSchemasPartialUpdate>[2]
        )) as unknown as ExternalDataSourceSchema
    },
    async reload(schemaId: string): Promise<void> {
        await externalDataSchemasReloadCreate(
            projectId(),
            schemaId,
            {} as Parameters<typeof externalDataSchemasReloadCreate>[2]
        )
    },
    async resync(schemaId: string): Promise<void> {
        await externalDataSchemasResyncCreate(
            projectId(),
            schemaId,
            {} as Parameters<typeof externalDataSchemasResyncCreate>[2]
        )
    },
    async cancel(schemaId: string): Promise<void> {
        await externalDataSchemasCancelCreate(projectId(), schemaId)
    },
    async incremental_fields(schemaId: string): Promise<SchemaIncrementalFieldsResponse> {
        return (await externalDataSchemasIncrementalFieldsCreate(
            projectId(),
            schemaId,
            {} as Parameters<typeof externalDataSchemasIncrementalFieldsCreate>[2]
        )) as unknown as SchemaIncrementalFieldsResponse
    },
    async delete_data(schemaId: string): Promise<SchemaIncrementalFieldsResponse> {
        return (await externalDataSchemasDeleteDataDestroy(
            projectId(),
            schemaId
        )) as unknown as SchemaIncrementalFieldsResponse
    },
}
