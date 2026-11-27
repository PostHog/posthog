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
    BroadcastOptionApi,
    CatalogFlagsResponseApi,
    CatalogReleasesResponseApi,
    FlagReleasesApi,
    ImportAllResponseApi,
    MergeReleasesApi,
    PaginatedReleaseDTOListApi,
    PatchedUpdateReleaseApi,
    ReleaseDTOApi,
    ReleasesBroadcastSearchRetrieveParams,
    ReleasesCatalogFlagsRetrieveParams,
    ReleasesCatalogReleasesRetrieveParams,
    ReleasesFlagSuggestionsRetrieveParams,
    ReleasesListParams,
    WriteReleaseApi,
} from './api.schemas'

export const getReleasesListUrl = (projectId: string, params?: ReleasesListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/releases/?${stringifiedParams}`
        : `/api/projects/${projectId}/releases/`
}

/**
 * List the releases of the project, oldest first.
 */
export const releasesList = async (
    projectId: string,
    params?: ReleasesListParams,
    options?: RequestInit
): Promise<PaginatedReleaseDTOListApi> => {
    return apiMutator<PaginatedReleaseDTOListApi>(getReleasesListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getReleasesCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/releases/`
}

/**
 * Create a release.
 */
export const releasesCreate = async (
    projectId: string,
    writeReleaseApi: WriteReleaseApi,
    options?: RequestInit
): Promise<ReleaseDTOApi> => {
    return apiMutator<ReleaseDTOApi>(getReleasesCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(writeReleaseApi),
    })
}

export const getReleasesRetrieveUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/releases/${id}/`
}

/**
 * Get one release with its linked flags, broadcasts, surveys and insights.
 */
export const releasesRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<ReleaseDTOApi> => {
    return apiMutator<ReleaseDTOApi>(getReleasesRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getReleasesPartialUpdateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/releases/${id}/`
}

/**
 * Change the name, description, owner or linked flags, broadcasts, surveys and insights of a release.
 */
export const releasesPartialUpdate = async (
    projectId: string,
    id: string,
    patchedUpdateReleaseApi?: PatchedUpdateReleaseApi,
    options?: RequestInit
): Promise<ReleaseDTOApi> => {
    return apiMutator<ReleaseDTOApi>(getReleasesPartialUpdateUrl(projectId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedUpdateReleaseApi),
    })
}

export const getReleasesDestroyUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/releases/${id}/`
}

/**
 * Delete a release. Its flags, experiments and early access features stay.
 */
export const releasesDestroy = async (projectId: string, id: string, options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getReleasesDestroyUrl(projectId, id), {
        ...options,
        method: 'DELETE',
    })
}

export const getReleasesMergeCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/releases/${id}/merge/`
}

/**
 * Merge other releases into this one. This release keeps its name, gains their links, then they are deleted.
 */
export const releasesMergeCreate = async (
    projectId: string,
    id: string,
    mergeReleasesApi: MergeReleasesApi,
    options?: RequestInit
): Promise<ReleaseDTOApi> => {
    return apiMutator<ReleaseDTOApi>(getReleasesMergeCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(mergeReleasesApi),
    })
}

export const getReleasesBroadcastSearchRetrieveUrl = (
    projectId: string,
    params?: ReleasesBroadcastSearchRetrieveParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/releases/broadcast_search/?${stringifiedParams}`
        : `/api/projects/${projectId}/releases/broadcast_search/`
}

/**
 * Search the broadcasts a release can link, returning only their ID, name and status.
 */
export const releasesBroadcastSearchRetrieve = async (
    projectId: string,
    params?: ReleasesBroadcastSearchRetrieveParams,
    options?: RequestInit
): Promise<BroadcastOptionApi[]> => {
    return apiMutator<BroadcastOptionApi[]>(getReleasesBroadcastSearchRetrieveUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getReleasesCatalogFlagsRetrieveUrl = (projectId: string, params?: ReleasesCatalogFlagsRetrieveParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/releases/catalog_flags/?${stringifiedParams}`
        : `/api/projects/${projectId}/releases/catalog_flags/`
}

/**
 * List the project's feature flags the caller can see, newest or oldest first, with only the fields a list shows.
 */
export const releasesCatalogFlagsRetrieve = async (
    projectId: string,
    params?: ReleasesCatalogFlagsRetrieveParams,
    options?: RequestInit
): Promise<CatalogFlagsResponseApi> => {
    return apiMutator<CatalogFlagsResponseApi>(getReleasesCatalogFlagsRetrieveUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getReleasesCatalogReleasesRetrieveUrl = (
    projectId: string,
    params?: ReleasesCatalogReleasesRetrieveParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/releases/catalog_releases/?${stringifiedParams}`
        : `/api/projects/${projectId}/releases/catalog_releases/`
}

/**
 * List the project's releases, newest or oldest first, with only the fields a list shows.
 */
export const releasesCatalogReleasesRetrieve = async (
    projectId: string,
    params?: ReleasesCatalogReleasesRetrieveParams,
    options?: RequestInit
): Promise<CatalogReleasesResponseApi> => {
    return apiMutator<CatalogReleasesResponseApi>(getReleasesCatalogReleasesRetrieveUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getReleasesFlagSuggestionsRetrieveUrl = (
    projectId: string,
    params: ReleasesFlagSuggestionsRetrieveParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/releases/flag_suggestions/?${stringifiedParams}`
        : `/api/projects/${projectId}/releases/flag_suggestions/`
}

/**
 * Find the releases a feature flag is in, and the existing releases it probably belongs to.
 */
export const releasesFlagSuggestionsRetrieve = async (
    projectId: string,
    params: ReleasesFlagSuggestionsRetrieveParams,
    options?: RequestInit
): Promise<FlagReleasesApi> => {
    return apiMutator<FlagReleasesApi>(getReleasesFlagSuggestionsRetrieveUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getReleasesImportAllCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/releases/import_all/`
}

/**
 * Set up releases for the whole project once: one per active flag. Later calls create nothing.
 */
export const releasesImportAllCreate = async (
    projectId: string,
    options?: RequestInit
): Promise<ImportAllResponseApi> => {
    return apiMutator<ImportAllResponseApi>(getReleasesImportAllCreateUrl(projectId), {
        ...options,
        method: 'POST',
    })
}
