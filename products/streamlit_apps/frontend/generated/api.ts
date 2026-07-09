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
    ActivateVersionRequestApi,
    ActivateVersionResponseApi,
    AppContractApi,
    AppVersionContractApi,
    CreateAppInputApi,
    PaginatedAppContractListApi,
    PatchedUpdateAppInputApi,
    StreamlitAppStatusApi,
    StreamlitAppVersionListApi,
    StreamlitAppsListParams,
    StreamlitConnectInfoApi,
    UpdateAppInputApi,
    UploadVersionRequestApi,
} from './api.schemas'

export const getStreamlitAppsListUrl = (projectId: string, params?: StreamlitAppsListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/streamlit_apps/?${stringifiedParams}`
        : `/api/projects/${projectId}/streamlit_apps/`
}

/**
 * @summary List streamlit apps
 */
export const streamlitAppsList = async (
    projectId: string,
    params?: StreamlitAppsListParams,
    options?: RequestInit
): Promise<PaginatedAppContractListApi> => {
    return apiMutator<PaginatedAppContractListApi>(getStreamlitAppsListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getStreamlitAppsCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/streamlit_apps/`
}

/**
 * @summary Create a streamlit app
 */
export const streamlitAppsCreate = async (
    projectId: string,
    createAppInputApi: CreateAppInputApi,
    options?: RequestInit
): Promise<AppContractApi> => {
    return apiMutator<AppContractApi>(getStreamlitAppsCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(createAppInputApi),
    })
}

export const getStreamlitAppsRetrieveUrl = (projectId: string, shortId: string) => {
    return `/api/projects/${projectId}/streamlit_apps/${shortId}/`
}

/**
 * @summary Retrieve a streamlit app
 */
export const streamlitAppsRetrieve = async (
    projectId: string,
    shortId: string,
    options?: RequestInit
): Promise<AppContractApi> => {
    return apiMutator<AppContractApi>(getStreamlitAppsRetrieveUrl(projectId, shortId), {
        ...options,
        method: 'GET',
    })
}

export const getStreamlitAppsUpdateUrl = (projectId: string, shortId: string) => {
    return `/api/projects/${projectId}/streamlit_apps/${shortId}/`
}

/**
 * @summary Update a streamlit app
 */
export const streamlitAppsUpdate = async (
    projectId: string,
    shortId: string,
    updateAppInputApi?: UpdateAppInputApi,
    options?: RequestInit
): Promise<AppContractApi> => {
    return apiMutator<AppContractApi>(getStreamlitAppsUpdateUrl(projectId, shortId), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(updateAppInputApi),
    })
}

export const getStreamlitAppsPartialUpdateUrl = (projectId: string, shortId: string) => {
    return `/api/projects/${projectId}/streamlit_apps/${shortId}/`
}

/**
 * @summary Partially update a streamlit app
 */
export const streamlitAppsPartialUpdate = async (
    projectId: string,
    shortId: string,
    patchedUpdateAppInputApi?: PatchedUpdateAppInputApi,
    options?: RequestInit
): Promise<AppContractApi> => {
    return apiMutator<AppContractApi>(getStreamlitAppsPartialUpdateUrl(projectId, shortId), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedUpdateAppInputApi),
    })
}

export const getStreamlitAppsDestroyUrl = (projectId: string, shortId: string) => {
    return `/api/projects/${projectId}/streamlit_apps/${shortId}/`
}

/**
 * @summary Delete a streamlit app
 */
export const streamlitAppsDestroy = async (
    projectId: string,
    shortId: string,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getStreamlitAppsDestroyUrl(projectId, shortId), {
        ...options,
        method: 'DELETE',
    })
}

export const getStreamlitAppsActivateVersionCreateUrl = (projectId: string, shortId: string) => {
    return `/api/projects/${projectId}/streamlit_apps/${shortId}/activate_version/`
}

/**
 * @summary Activate an existing app version
 */
export const streamlitAppsActivateVersionCreate = async (
    projectId: string,
    shortId: string,
    activateVersionRequestApi: ActivateVersionRequestApi,
    options?: RequestInit
): Promise<ActivateVersionResponseApi> => {
    return apiMutator<ActivateVersionResponseApi>(getStreamlitAppsActivateVersionCreateUrl(projectId, shortId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(activateVersionRequestApi),
    })
}

export const getStreamlitAppsConnectInfoRetrieveUrl = (projectId: string, shortId: string) => {
    return `/api/projects/${projectId}/streamlit_apps/${shortId}/connect_info/`
}

/**
 * @summary Get iframe connection info for a running app
 */
export const streamlitAppsConnectInfoRetrieve = async (
    projectId: string,
    shortId: string,
    options?: RequestInit
): Promise<StreamlitConnectInfoApi> => {
    return apiMutator<StreamlitConnectInfoApi>(getStreamlitAppsConnectInfoRetrieveUrl(projectId, shortId), {
        ...options,
        method: 'GET',
    })
}

export const getStreamlitAppsRestartCreateUrl = (projectId: string, shortId: string) => {
    return `/api/projects/${projectId}/streamlit_apps/${shortId}/restart/`
}

/**
 * @summary Restart the app sandbox
 */
export const streamlitAppsRestartCreate = async (
    projectId: string,
    shortId: string,
    options?: RequestInit
): Promise<AppContractApi> => {
    return apiMutator<AppContractApi>(getStreamlitAppsRestartCreateUrl(projectId, shortId), {
        ...options,
        method: 'POST',
    })
}

export const getStreamlitAppsStartCreateUrl = (projectId: string, shortId: string) => {
    return `/api/projects/${projectId}/streamlit_apps/${shortId}/start/`
}

/**
 * @summary Start the app sandbox
 */
export const streamlitAppsStartCreate = async (
    projectId: string,
    shortId: string,
    options?: RequestInit
): Promise<AppContractApi> => {
    return apiMutator<AppContractApi>(getStreamlitAppsStartCreateUrl(projectId, shortId), {
        ...options,
        method: 'POST',
    })
}

export const getStreamlitAppsStatusRetrieveUrl = (projectId: string, shortId: string) => {
    return `/api/projects/${projectId}/streamlit_apps/${shortId}/status/`
}

/**
 * @summary Get app sandbox status
 */
export const streamlitAppsStatusRetrieve = async (
    projectId: string,
    shortId: string,
    options?: RequestInit
): Promise<StreamlitAppStatusApi> => {
    return apiMutator<StreamlitAppStatusApi>(getStreamlitAppsStatusRetrieveUrl(projectId, shortId), {
        ...options,
        method: 'GET',
    })
}

export const getStreamlitAppsStopCreateUrl = (projectId: string, shortId: string) => {
    return `/api/projects/${projectId}/streamlit_apps/${shortId}/stop/`
}

/**
 * @summary Stop the app sandbox
 */
export const streamlitAppsStopCreate = async (
    projectId: string,
    shortId: string,
    options?: RequestInit
): Promise<AppContractApi> => {
    return apiMutator<AppContractApi>(getStreamlitAppsStopCreateUrl(projectId, shortId), {
        ...options,
        method: 'POST',
    })
}

export const getStreamlitAppsUploadVersionCreateUrl = (projectId: string, shortId: string) => {
    return `/api/projects/${projectId}/streamlit_apps/${shortId}/upload_version/`
}

/**
 * @summary Upload a new app version
 */
export const streamlitAppsUploadVersionCreate = async (
    projectId: string,
    shortId: string,
    uploadVersionRequestApi: UploadVersionRequestApi,
    options?: RequestInit
): Promise<AppVersionContractApi> => {
    return apiMutator<AppVersionContractApi>(getStreamlitAppsUploadVersionCreateUrl(projectId, shortId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(uploadVersionRequestApi),
    })
}

export const getStreamlitAppsVersionsRetrieveUrl = (projectId: string, shortId: string) => {
    return `/api/projects/${projectId}/streamlit_apps/${shortId}/versions/`
}

/**
 * @summary List app versions
 */
export const streamlitAppsVersionsRetrieve = async (
    projectId: string,
    shortId: string,
    options?: RequestInit
): Promise<StreamlitAppVersionListApi> => {
    return apiMutator<StreamlitAppVersionListApi>(getStreamlitAppsVersionsRetrieveUrl(projectId, shortId), {
        ...options,
        method: 'GET',
    })
}
