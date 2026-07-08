import { apiMutator } from '../../../../frontend/src/lib/api-orval-mutator'
/**
 * Auto-generated from the Django backend OpenAPI schema.
 * To modify these types, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
import type {
    DatabaseSchemaRequestApi,
    DraftCustomManifestRequestApi,
    DraftCustomManifestResponseApi,
    ExternalDataSchemaApi,
    ExternalDataSchemasListParams,
    ExternalDataSchemasLogsRetrieveParams,
    ExternalDataSourceCreateApi,
    ExternalDataSourceSerializersApi,
    ExternalDataSourcesBulkUpdateSchemasPartialUpdateParams,
    ExternalDataSourcesCheckCdcPrerequisitesCreate200,
    ExternalDataSourcesConnectLinkRetrieveParams,
    ExternalDataSourcesConnectionsListParams,
    ExternalDataSourcesListParams,
    ExternalDataSourcesOauthAccountsRetrieveParams,
    ExternalDataSourcesStoredCredentialsListParams,
    ExternalDataSourcesWizardRetrieveParams,
    IntegrationAccountsResponseApi,
    PaginatedExternalDataSchemaListApi,
    PaginatedExternalDataSourceConnectionOptionListApi,
    PaginatedExternalDataSourceSerializersListApi,
    PatchedExternalDataSchemaApi,
    PatchedExternalDataSourceBulkUpdateSchemasApi,
    PatchedExternalDataSourceSerializersApi,
    SourceConnectLinkApi,
    SourceCredentialApi,
    SourceCredentialCreateApi,
    SourcePreviewRequestApi,
    SourcePreviewResponseApi,
    SourceSetupApi,
    SourceSetupResponseApi,
} from './api.schemas'

// https://stackoverflow.com/questions/49579094/typescript-conditional-types-filter-out-readonly-properties-pick-only-requir/49579497#49579497
type IfEquals<X, Y, A = X, B = never> = (<T>() => T extends X ? 1 : 2) extends <T>() => T extends Y ? 1 : 2 ? A : B

type WritableKeys<T> = {
    [P in keyof T]-?: IfEquals<{ [Q in P]: T[P] }, { -readonly [Q in P]: T[P] }, P>
}[keyof T]

type UnionToIntersection<U> = (U extends any ? (k: U) => void : never) extends (k: infer I) => void ? I : never
type DistributeReadOnlyOverUnions<T> = T extends any ? NonReadonly<T> : never

type Writable<T> = Pick<T, WritableKeys<T>>
type NonReadonly<T> = [T] extends [UnionToIntersection<T>]
    ? {
          [P in keyof Writable<T>]: T[P] extends object ? NonReadonly<NonNullable<T[P]>> : T[P]
      }
    : DistributeReadOnlyOverUnions<T>

export const getExternalDataSchemasListUrl = (projectId: string, params?: ExternalDataSchemasListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/external_data_schemas/?${stringifiedParams}`
        : `/api/projects/${projectId}/external_data_schemas/`
}

export const externalDataSchemasList = async (
    projectId: string,
    params?: ExternalDataSchemasListParams,
    options?: RequestInit
): Promise<PaginatedExternalDataSchemaListApi> => {
    return apiMutator<PaginatedExternalDataSchemaListApi>(getExternalDataSchemasListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getExternalDataSchemasCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/external_data_schemas/`
}

export const externalDataSchemasCreate = async (
    projectId: string,
    externalDataSchemaApi?: NonReadonly<ExternalDataSchemaApi>,
    options?: RequestInit
): Promise<ExternalDataSchemaApi> => {
    return apiMutator<ExternalDataSchemaApi>(getExternalDataSchemasCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(externalDataSchemaApi),
    })
}

export const getExternalDataSchemasRetrieveUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/external_data_schemas/${id}/`
}

export const externalDataSchemasRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<ExternalDataSchemaApi> => {
    return apiMutator<ExternalDataSchemaApi>(getExternalDataSchemasRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getExternalDataSchemasUpdateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/external_data_schemas/${id}/`
}

export const externalDataSchemasUpdate = async (
    projectId: string,
    id: string,
    externalDataSchemaApi?: NonReadonly<ExternalDataSchemaApi>,
    options?: RequestInit
): Promise<ExternalDataSchemaApi> => {
    return apiMutator<ExternalDataSchemaApi>(getExternalDataSchemasUpdateUrl(projectId, id), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(externalDataSchemaApi),
    })
}

export const getExternalDataSchemasPartialUpdateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/external_data_schemas/${id}/`
}

export const externalDataSchemasPartialUpdate = async (
    projectId: string,
    id: string,
    patchedExternalDataSchemaApi?: NonReadonly<PatchedExternalDataSchemaApi>,
    options?: RequestInit
): Promise<ExternalDataSchemaApi> => {
    return apiMutator<ExternalDataSchemaApi>(getExternalDataSchemasPartialUpdateUrl(projectId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedExternalDataSchemaApi),
    })
}

export const getExternalDataSchemasDestroyUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/external_data_schemas/${id}/`
}

export const externalDataSchemasDestroy = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getExternalDataSchemasDestroyUrl(projectId, id), {
        ...options,
        method: 'DELETE',
    })
}

export const getExternalDataSchemasCancelCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/external_data_schemas/${id}/cancel/`
}

export const externalDataSchemasCancelCreate = async (
    projectId: string,
    id: string,
    externalDataSchemaApi?: NonReadonly<ExternalDataSchemaApi>,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getExternalDataSchemasCancelCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(externalDataSchemaApi),
    })
}

export const getExternalDataSchemasDeleteDataDestroyUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/external_data_schemas/${id}/delete_data/`
}

export const externalDataSchemasDeleteDataDestroy = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getExternalDataSchemasDeleteDataDestroyUrl(projectId, id), {
        ...options,
        method: 'DELETE',
    })
}

export const getExternalDataSchemasIncrementalFieldsCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/external_data_schemas/${id}/incremental_fields/`
}

export const externalDataSchemasIncrementalFieldsCreate = async (
    projectId: string,
    id: string,
    externalDataSchemaApi?: NonReadonly<ExternalDataSchemaApi>,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getExternalDataSchemasIncrementalFieldsCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(externalDataSchemaApi),
    })
}

export const getExternalDataSchemasLogsRetrieveUrl = (
    projectId: string,
    id: string,
    params?: ExternalDataSchemasLogsRetrieveParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/external_data_schemas/${id}/logs/?${stringifiedParams}`
        : `/api/projects/${projectId}/external_data_schemas/${id}/logs/`
}

export const externalDataSchemasLogsRetrieve = async (
    projectId: string,
    id: string,
    params?: ExternalDataSchemasLogsRetrieveParams,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getExternalDataSchemasLogsRetrieveUrl(projectId, id, params), {
        ...options,
        method: 'GET',
    })
}

export const getExternalDataSchemasReloadCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/external_data_schemas/${id}/reload/`
}

export const externalDataSchemasReloadCreate = async (
    projectId: string,
    id: string,
    externalDataSchemaApi?: NonReadonly<ExternalDataSchemaApi>,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getExternalDataSchemasReloadCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(externalDataSchemaApi),
    })
}

export const getExternalDataSchemasResyncCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/external_data_schemas/${id}/resync/`
}

export const externalDataSchemasResyncCreate = async (
    projectId: string,
    id: string,
    externalDataSchemaApi?: NonReadonly<ExternalDataSchemaApi>,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getExternalDataSchemasResyncCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(externalDataSchemaApi),
    })
}

export const getExternalDataSourcesListUrl = (projectId: string, params?: ExternalDataSourcesListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/external_data_sources/?${stringifiedParams}`
        : `/api/projects/${projectId}/external_data_sources/`
}

/**
 * Create, Read, Update and Delete External data Sources.
 */
export const externalDataSourcesList = async (
    projectId: string,
    params?: ExternalDataSourcesListParams,
    options?: RequestInit
): Promise<PaginatedExternalDataSourceSerializersListApi> => {
    return apiMutator<PaginatedExternalDataSourceSerializersListApi>(getExternalDataSourcesListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getExternalDataSourcesCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/external_data_sources/`
}

/**
 * Create, Read, Update and Delete External data Sources.
 */
export const externalDataSourcesCreate = async (
    projectId: string,
    externalDataSourceCreateApi: ExternalDataSourceCreateApi,
    options?: RequestInit
): Promise<ExternalDataSourceSerializersApi> => {
    return apiMutator<ExternalDataSourceSerializersApi>(getExternalDataSourcesCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(externalDataSourceCreateApi),
    })
}

export const getExternalDataSourcesRetrieveUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/external_data_sources/${id}/`
}

/**
 * Create, Read, Update and Delete External data Sources.
 */
export const externalDataSourcesRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<ExternalDataSourceSerializersApi> => {
    return apiMutator<ExternalDataSourceSerializersApi>(getExternalDataSourcesRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getExternalDataSourcesUpdateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/external_data_sources/${id}/`
}

/**
 * Create, Read, Update and Delete External data Sources.
 */
export const externalDataSourcesUpdate = async (
    projectId: string,
    id: string,
    externalDataSourceSerializersApi: NonReadonly<ExternalDataSourceSerializersApi>,
    options?: RequestInit
): Promise<ExternalDataSourceSerializersApi> => {
    return apiMutator<ExternalDataSourceSerializersApi>(getExternalDataSourcesUpdateUrl(projectId, id), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(externalDataSourceSerializersApi),
    })
}

export const getExternalDataSourcesPartialUpdateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/external_data_sources/${id}/`
}

/**
 * Create, Read, Update and Delete External data Sources.
 */
export const externalDataSourcesPartialUpdate = async (
    projectId: string,
    id: string,
    patchedExternalDataSourceSerializersApi?: NonReadonly<PatchedExternalDataSourceSerializersApi>,
    options?: RequestInit
): Promise<ExternalDataSourceSerializersApi> => {
    return apiMutator<ExternalDataSourceSerializersApi>(getExternalDataSourcesPartialUpdateUrl(projectId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedExternalDataSourceSerializersApi),
    })
}

export const getExternalDataSourcesDestroyUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/external_data_sources/${id}/`
}

/**
 * Create, Read, Update and Delete External data Sources.
 */
export const externalDataSourcesDestroy = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getExternalDataSourcesDestroyUrl(projectId, id), {
        ...options,
        method: 'DELETE',
    })
}

export const getExternalDataSourcesBulkUpdateSchemasPartialUpdateUrl = (
    projectId: string,
    id: string,
    params?: ExternalDataSourcesBulkUpdateSchemasPartialUpdateParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/external_data_sources/${id}/bulk_update_schemas/?${stringifiedParams}`
        : `/api/projects/${projectId}/external_data_sources/${id}/bulk_update_schemas/`
}

/**
 * Create, Read, Update and Delete External data Sources.
 */
export const externalDataSourcesBulkUpdateSchemasPartialUpdate = async (
    projectId: string,
    id: string,
    patchedExternalDataSourceBulkUpdateSchemasApi?: PatchedExternalDataSourceBulkUpdateSchemasApi,
    params?: ExternalDataSourcesBulkUpdateSchemasPartialUpdateParams,
    options?: RequestInit
): Promise<PaginatedExternalDataSchemaListApi> => {
    return apiMutator<PaginatedExternalDataSchemaListApi>(
        getExternalDataSourcesBulkUpdateSchemasPartialUpdateUrl(projectId, id, params),
        {
            ...options,
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(patchedExternalDataSourceBulkUpdateSchemasApi),
        }
    )
}

export const getExternalDataSourcesCdcStatusRetrieveUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/external_data_sources/${id}/cdc_status/`
}

/**
 * Live CDC health for an existing source: slot/publication existence and WAL lag.
 *
 * Reads from the source DB via the engine adapter. Returns ``{"enabled": false}``
 * when CDC is off, or the stored config plus live ``slot_exists`` /
 * ``publication_exists`` / ``lag_bytes`` when on. 400s if the source DB is
 * unreachable so the UI can show a degraded/unreachable state.
 */
export const externalDataSourcesCdcStatusRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getExternalDataSourcesCdcStatusRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getExternalDataSourcesCheckCdcPrerequisitesForSourceCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/external_data_sources/${id}/check_cdc_prerequisites_for_source/`
}

/**
 * Validate CDC prerequisites for an existing source using its stored credentials.
 *
 * The detail=False ``check_cdc_prerequisites`` action is for the creation wizard,
 * where the client still holds the raw connection config (incl. password) in the
 * form. On the Configuration page the source already exists and secret fields are
 * stripped from API responses — so the client can't supply them. This reads the
 * stored (encrypted) credentials from the DB via the adapter instead.
 *
 * Body params: ``cdc_management_mode`` (``"posthog"`` | ``"self_managed"``),
 * ``cdc_slot_name`` (optional), ``cdc_publication_name`` (optional).
 */
export const externalDataSourcesCheckCdcPrerequisitesForSourceCreate = async (
    projectId: string,
    id: string,
    externalDataSourceSerializersApi: NonReadonly<ExternalDataSourceSerializersApi>,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getExternalDataSourcesCheckCdcPrerequisitesForSourceCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(externalDataSourceSerializersApi),
    })
}

export const getExternalDataSourcesCreateWebhookCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/external_data_sources/${id}/create_webhook/`
}

/**
 * Create, Read, Update and Delete External data Sources.
 */
export const externalDataSourcesCreateWebhookCreate = async (
    projectId: string,
    id: string,
    externalDataSourceSerializersApi: NonReadonly<ExternalDataSourceSerializersApi>,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getExternalDataSourcesCreateWebhookCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(externalDataSourceSerializersApi),
    })
}

export const getExternalDataSourcesDeleteWebhookCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/external_data_sources/${id}/delete_webhook/`
}

/**
 * Create, Read, Update and Delete External data Sources.
 */
export const externalDataSourcesDeleteWebhookCreate = async (
    projectId: string,
    id: string,
    externalDataSourceSerializersApi: NonReadonly<ExternalDataSourceSerializersApi>,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getExternalDataSourcesDeleteWebhookCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(externalDataSourceSerializersApi),
    })
}

export const getExternalDataSourcesDisableCdcCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/external_data_sources/${id}/disable_cdc/`
}

/**
 * Disable CDC on an existing source.
 *
 * Cancels any running CDC extraction workflow, deletes the extraction schedule,
 * delegates engine-side teardown to the source's adapter (drops slot/publication
 * for Postgres; equivalent for other engines), clears ``cdc_*`` keys from
 * ``job_inputs``, soft-deletes companion CDC tables, and sets all CDC schemas to
 * ``sync_type=None``, ``should_sync=False`` so the user must pick a new sync
 * strategy before they resume.
 */
export const externalDataSourcesDisableCdcCreate = async (
    projectId: string,
    id: string,
    externalDataSourceSerializersApi: NonReadonly<ExternalDataSourceSerializersApi>,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getExternalDataSourcesDisableCdcCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(externalDataSourceSerializersApi),
    })
}

export const getExternalDataSourcesEnableCdcCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/external_data_sources/${id}/enable_cdc/`
}

/**
 * Enable CDC on an existing source.
 *
 * Provisions engine-side CDC resources via the source's adapter, writes the CDC
 * config into ``source.job_inputs``, and ensures the CDC extraction schedule
 * exists. Re-runs prereq checks server-side so we never trust a stale
 * client-side check.
 *
 * Body params: ``cdc_management_mode`` (``"posthog"`` | ``"self_managed"``),
 * plus engine-specific identifier hints (e.g. ``cdc_slot_name``,
 * ``cdc_publication_name`` for Postgres). Universal tuning fields:
 * ``cdc_auto_drop_slot`` (optional bool), ``cdc_lag_warning_threshold_mb``
 * (optional int), ``cdc_lag_critical_threshold_mb`` (optional int).
 */
export const externalDataSourcesEnableCdcCreate = async (
    projectId: string,
    id: string,
    externalDataSourceSerializersApi: NonReadonly<ExternalDataSourceSerializersApi>,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getExternalDataSourcesEnableCdcCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(externalDataSourceSerializersApi),
    })
}

export const getExternalDataSourcesJobsRetrieveUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/external_data_sources/${id}/jobs/`
}

/**
 * Create, Read, Update and Delete External data Sources.
 */
export const externalDataSourcesJobsRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getExternalDataSourcesJobsRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getExternalDataSourcesRefreshSchemasCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/external_data_sources/${id}/refresh_schemas/`
}

/**
 * Fetch current schema/table list from the source and create any new ExternalDataSchema rows (no data sync).
 */
export const externalDataSourcesRefreshSchemasCreate = async (
    projectId: string,
    id: string,
    externalDataSourceSerializersApi: NonReadonly<ExternalDataSourceSerializersApi>,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getExternalDataSourcesRefreshSchemasCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(externalDataSourceSerializersApi),
    })
}

export const getExternalDataSourcesReloadCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/external_data_sources/${id}/reload/`
}

/**
 * Create, Read, Update and Delete External data Sources.
 */
export const externalDataSourcesReloadCreate = async (
    projectId: string,
    id: string,
    externalDataSourceSerializersApi: NonReadonly<ExternalDataSourceSerializersApi>,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getExternalDataSourcesReloadCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(externalDataSourceSerializersApi),
    })
}

export const getExternalDataSourcesRevenueAnalyticsConfigPartialUpdateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/external_data_sources/${id}/revenue_analytics_config/`
}

/**
 * Update the revenue analytics configuration and return the full external data source.
 */
export const externalDataSourcesRevenueAnalyticsConfigPartialUpdate = async (
    projectId: string,
    id: string,
    patchedExternalDataSourceSerializersApi?: NonReadonly<PatchedExternalDataSourceSerializersApi>,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getExternalDataSourcesRevenueAnalyticsConfigPartialUpdateUrl(projectId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedExternalDataSourceSerializersApi),
    })
}

export const getExternalDataSourcesUpdateCdcSettingsCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/external_data_sources/${id}/update_cdc_settings/`
}

/**
 * Update CDC tuning fields without enabling/disabling.
 *
 * Lets users edit ``cdc_auto_drop_slot``, ``cdc_lag_warning_threshold_mb``, and
 * ``cdc_lag_critical_threshold_mb`` independently. These fields are universal
 * across engines. Engine-specific identifiers (slot name, management mode, …)
 * are immutable post-enable — switching them requires disable + enable.
 */
export const externalDataSourcesUpdateCdcSettingsCreate = async (
    projectId: string,
    id: string,
    externalDataSourceSerializersApi: NonReadonly<ExternalDataSourceSerializersApi>,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getExternalDataSourcesUpdateCdcSettingsCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(externalDataSourceSerializersApi),
    })
}

export const getExternalDataSourcesUpdateWebhookInputsCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/external_data_sources/${id}/update_webhook_inputs/`
}

/**
 * Create, Read, Update and Delete External data Sources.
 */
export const externalDataSourcesUpdateWebhookInputsCreate = async (
    projectId: string,
    id: string,
    externalDataSourceSerializersApi: NonReadonly<ExternalDataSourceSerializersApi>,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getExternalDataSourcesUpdateWebhookInputsCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(externalDataSourceSerializersApi),
    })
}

export const getExternalDataSourcesWebhookInfoRetrieveUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/external_data_sources/${id}/webhook_info/`
}

/**
 * Create, Read, Update and Delete External data Sources.
 */
export const externalDataSourcesWebhookInfoRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getExternalDataSourcesWebhookInfoRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getExternalDataSourcesCheckCdcPrerequisitesCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/external_data_sources/check_cdc_prerequisites/`
}

/**
 * Validate CDC prerequisites against a live Postgres connection.
 *
 * Used by the source wizard to surface ✅/❌ checks before source creation,
 * and by the self-managed setup popup to verify user-created publications.
 */
export const externalDataSourcesCheckCdcPrerequisitesCreate = async (
    projectId: string,
    options?: RequestInit
): Promise<ExternalDataSourcesCheckCdcPrerequisitesCreate200> => {
    return apiMutator<ExternalDataSourcesCheckCdcPrerequisitesCreate200>(
        getExternalDataSourcesCheckCdcPrerequisitesCreateUrl(projectId),
        {
            ...options,
            method: 'POST',
        }
    )
}

export const getExternalDataSourcesConnectLinkRetrieveUrl = (
    projectId: string,
    params: ExternalDataSourcesConnectLinkRetrieveParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/external_data_sources/connect_link/?${stringifiedParams}`
        : `/api/projects/${projectId}/external_data_sources/connect_link/`
}

/**
 * Return a secure browser link for connecting a data warehouse source.
 *
 * The link opens a minimal connect page rendering the source's full connection form — OAuth options
 * included — with no table selection and no source creation. The user authenticates in their browser,
 * secrets never pass through the agent, and the agent finishes setup afterwards by passing the stored
 * credential id to data-warehouse-source-setup.
 */
export const externalDataSourcesConnectLinkRetrieve = async (
    projectId: string,
    params: ExternalDataSourcesConnectLinkRetrieveParams,
    options?: RequestInit
): Promise<SourceConnectLinkApi> => {
    return apiMutator<SourceConnectLinkApi>(getExternalDataSourcesConnectLinkRetrieveUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getExternalDataSourcesConnectionsListUrl = (
    projectId: string,
    params?: ExternalDataSourcesConnectionsListParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/external_data_sources/connections/?${stringifiedParams}`
        : `/api/projects/${projectId}/external_data_sources/connections/`
}

/**
 * Create, Read, Update and Delete External data Sources.
 */
export const externalDataSourcesConnectionsList = async (
    projectId: string,
    params?: ExternalDataSourcesConnectionsListParams,
    options?: RequestInit
): Promise<PaginatedExternalDataSourceConnectionOptionListApi> => {
    return apiMutator<PaginatedExternalDataSourceConnectionOptionListApi>(
        getExternalDataSourcesConnectionsListUrl(projectId, params),
        {
            ...options,
            method: 'GET',
        }
    )
}

export const getExternalDataSourcesDatabaseSchemaCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/external_data_sources/database_schema/`
}

/**
 * Create, Read, Update and Delete External data Sources.
 */
export const externalDataSourcesDatabaseSchemaCreate = async (
    projectId: string,
    databaseSchemaRequestApi: DatabaseSchemaRequestApi,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getExternalDataSourcesDatabaseSchemaCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(databaseSchemaRequestApi),
    })
}

export const getExternalDataSourcesDraftCustomManifestCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/external_data_sources/draft_custom_manifest/`
}

/**
 * Draft a Custom REST source manifest from API documentation using an LLM.
 *
 * Reads the docs (a URL fetched server-side, or pasted text / OpenAPI spec), asks the model to
 * author a RESTAPIConfig manifest, and validates it against the create-path checks — repairing
 * against validation errors up to a small budget. Returns the manifest for the user to review
 * and tweak in the builder before creating the source; it does NOT create anything. Gated by the
 * `dwh-custom-source-ai-builder` flag, and requires the org to have approved AI data processing,
 * since the docs are sent to the LLM gateway.
 */
export const externalDataSourcesDraftCustomManifestCreate = async (
    projectId: string,
    draftCustomManifestRequestApi?: DraftCustomManifestRequestApi,
    options?: RequestInit
): Promise<DraftCustomManifestResponseApi> => {
    return apiMutator<DraftCustomManifestResponseApi>(getExternalDataSourcesDraftCustomManifestCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(draftCustomManifestRequestApi),
    })
}

export const getExternalDataSourcesOauthAccountsRetrieveUrl = (
    projectId: string,
    params: ExternalDataSourcesOauthAccountsRetrieveParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/external_data_sources/oauth_accounts/?${stringifiedParams}`
        : `/api/projects/${projectId}/external_data_sources/oauth_accounts/`
}

/**
 * List the accounts/properties a connected OAuth integration exposes, in the shared
 * IntegrationAccount shape. The logic lives in each source (via OAuthMixin.get_oauth_accounts);
 * this endpoint just routes by source type and serializes the result.
 */
export const externalDataSourcesOauthAccountsRetrieve = async (
    projectId: string,
    params: ExternalDataSourcesOauthAccountsRetrieveParams,
    options?: RequestInit
): Promise<IntegrationAccountsResponseApi> => {
    return apiMutator<IntegrationAccountsResponseApi>(
        getExternalDataSourcesOauthAccountsRetrieveUrl(projectId, params),
        {
            ...options,
            method: 'GET',
        }
    )
}

export const getExternalDataSourcesPreviewResourceCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/external_data_sources/preview_resource/`
}

/**
 * Read a bounded sample of rows for one resource of a Custom REST source.
 *
 * Lets a manifest author verify `data_selector`, `primary_key`, and the incremental
 * `cursor_path` against live data before creating the source. Only `source_type: "Custom"`
 * is supported — other source types return 400. The read is bounded (single page per
 * resource, capped row count, short timeouts, no redirects). Manifest, validation, and SSRF
 * problems return 400; a live fetch failure returns 200 with `error` set and empty `rows`.
 */
export const externalDataSourcesPreviewResourceCreate = async (
    projectId: string,
    sourcePreviewRequestApi: SourcePreviewRequestApi,
    options?: RequestInit
): Promise<SourcePreviewResponseApi> => {
    return apiMutator<SourcePreviewResponseApi>(getExternalDataSourcesPreviewResourceCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(sourcePreviewRequestApi),
    })
}

export const getExternalDataSourcesSetupCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/external_data_sources/setup/`
}

/**
 * One-shot data warehouse source setup.
 *
 * Validate credentials, discover available tables, enable them all with sensible sync defaults
 * (incremental where supported, else append, else full refresh), and create the source in a single
 * call — the caller never has to assemble a `schemas` array. For sources that support webhooks
 * (e.g. Stripe), a webhook is auto-registered after creation: on success webhook-capable tables
 * switch to real-time webhook sync (unlocking webhook-only tables); on failure the polling
 * defaults stay in place. For fine-grained table/sync control, use the lower-level
 * `database_schema` + `create` flow instead.
 */
export const externalDataSourcesSetupCreate = async (
    projectId: string,
    sourceSetupApi: SourceSetupApi,
    options?: RequestInit
): Promise<SourceSetupResponseApi> => {
    return apiMutator<SourceSetupResponseApi>(getExternalDataSourcesSetupCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(sourceSetupApi),
    })
}

export const getExternalDataSourcesSourcePrefixCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/external_data_sources/source_prefix/`
}

/**
 * Create, Read, Update and Delete External data Sources.
 */
export const externalDataSourcesSourcePrefixCreate = async (
    projectId: string,
    externalDataSourceSerializersApi: NonReadonly<ExternalDataSourceSerializersApi>,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getExternalDataSourcesSourcePrefixCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(externalDataSourceSerializersApi),
    })
}

export const getExternalDataSourcesStoreCredentialsCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/external_data_sources/store_credentials/`
}

/**
 * Validate and store credentials for a data warehouse source without creating the source.
 *
 * Backs the source connect page: the user enters credentials directly in PostHog, they are
 * checked against a live connection, then stashed encrypted in a temporary store. The returned
 * credential id can be passed to `setup` as {'credential_id': <id>} to create the source — so
 * secrets never travel through an agent conversation. The stash is single-use: it is deleted
 * as soon as `setup` consumes it, and expires after 24 hours if never consumed.
 */
export const externalDataSourcesStoreCredentialsCreate = async (
    projectId: string,
    sourceCredentialCreateApi: SourceCredentialCreateApi,
    options?: RequestInit
): Promise<SourceCredentialApi> => {
    return apiMutator<SourceCredentialApi>(getExternalDataSourcesStoreCredentialsCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(sourceCredentialCreateApi),
    })
}

export const getExternalDataSourcesStoredCredentialsListUrl = (
    projectId: string,
    params?: ExternalDataSourcesStoredCredentialsListParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/external_data_sources/stored_credentials/?${stringifiedParams}`
        : `/api/projects/${projectId}/external_data_sources/stored_credentials/`
}

/**
 * List credentials stored via the source connect page that haven't been consumed yet.
 *
 * Returns metadata only (id, source type, timestamps) — never the secrets themselves. Stored
 * credentials are temporary: they disappear once consumed by `setup` or when they expire.
 * Newest first, so after a user confirms they've finished the connect page, the first entry
 * for the source type is the one to pass to `setup`.
 */
export const externalDataSourcesStoredCredentialsList = async (
    projectId: string,
    params?: ExternalDataSourcesStoredCredentialsListParams,
    options?: RequestInit
): Promise<SourceCredentialApi[]> => {
    return apiMutator<SourceCredentialApi[]>(getExternalDataSourcesStoredCredentialsListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getExternalDataSourcesWizardRetrieveUrl = (
    projectId: string,
    params?: ExternalDataSourcesWizardRetrieveParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/external_data_sources/wizard/?${stringifiedParams}`
        : `/api/projects/${projectId}/external_data_sources/wizard/`
}

/**
 * Create, Read, Update and Delete External data Sources.
 */
export const externalDataSourcesWizardRetrieve = async (
    projectId: string,
    params?: ExternalDataSourcesWizardRetrieveParams,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getExternalDataSourcesWizardRetrieveUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}
