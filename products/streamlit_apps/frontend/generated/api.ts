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
    PaginatedStreamlitAppMinimalListApi,
    PatchedStreamlitAppApi,
    StreamlitAppApi,
    StreamlitAppStatusApi,
    StreamlitAppVersionApi,
    StreamlitAppVersionListApi,
    StreamlitAppsListParams,
    StreamlitConnectInfoApi,
    UploadVersionRequestApi,
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

export const streamlitAppsList = async (
    projectId: string,
    params?: StreamlitAppsListParams,
    options?: RequestInit
): Promise<PaginatedStreamlitAppMinimalListApi> => {
    return apiMutator<PaginatedStreamlitAppMinimalListApi>(getStreamlitAppsListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getStreamlitAppsCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/streamlit_apps/`
}

export const streamlitAppsCreate = async (
    projectId: string,
    streamlitAppApi: NonReadonly<StreamlitAppApi>,
    options?: RequestInit
): Promise<StreamlitAppApi> => {
    return apiMutator<StreamlitAppApi>(getStreamlitAppsCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(streamlitAppApi),
    })
}

export const getStreamlitAppsRetrieveUrl = (projectId: string, shortId: string) => {
    return `/api/projects/${projectId}/streamlit_apps/${shortId}/`
}

export const streamlitAppsRetrieve = async (
    projectId: string,
    shortId: string,
    options?: RequestInit
): Promise<StreamlitAppApi> => {
    return apiMutator<StreamlitAppApi>(getStreamlitAppsRetrieveUrl(projectId, shortId), {
        ...options,
        method: 'GET',
    })
}

export const getStreamlitAppsUpdateUrl = (projectId: string, shortId: string) => {
    return `/api/projects/${projectId}/streamlit_apps/${shortId}/`
}

export const streamlitAppsUpdate = async (
    projectId: string,
    shortId: string,
    streamlitAppApi: NonReadonly<StreamlitAppApi>,
    options?: RequestInit
): Promise<StreamlitAppApi> => {
    return apiMutator<StreamlitAppApi>(getStreamlitAppsUpdateUrl(projectId, shortId), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(streamlitAppApi),
    })
}

export const getStreamlitAppsPartialUpdateUrl = (projectId: string, shortId: string) => {
    return `/api/projects/${projectId}/streamlit_apps/${shortId}/`
}

export const streamlitAppsPartialUpdate = async (
    projectId: string,
    shortId: string,
    patchedStreamlitAppApi?: NonReadonly<PatchedStreamlitAppApi>,
    options?: RequestInit
): Promise<StreamlitAppApi> => {
    return apiMutator<StreamlitAppApi>(getStreamlitAppsPartialUpdateUrl(projectId, shortId), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedStreamlitAppApi),
    })
}

export const getStreamlitAppsDestroyUrl = (projectId: string, shortId: string) => {
    return `/api/projects/${projectId}/streamlit_apps/${shortId}/`
}

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
): Promise<StreamlitAppApi> => {
    return apiMutator<StreamlitAppApi>(getStreamlitAppsRestartCreateUrl(projectId, shortId), {
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
): Promise<StreamlitAppApi> => {
    return apiMutator<StreamlitAppApi>(getStreamlitAppsStartCreateUrl(projectId, shortId), {
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
): Promise<StreamlitAppApi> => {
    return apiMutator<StreamlitAppApi>(getStreamlitAppsStopCreateUrl(projectId, shortId), {
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
): Promise<StreamlitAppVersionApi> => {
    return apiMutator<StreamlitAppVersionApi>(getStreamlitAppsUploadVersionCreateUrl(projectId, shortId), {
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
