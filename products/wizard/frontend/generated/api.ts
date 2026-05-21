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
    PaginatedWizardSessionListApi,
    PatchedWizardSessionApi,
    WizardListParams,
    WizardSessionApi,
    WizardSessionsListParams,
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

export const getWizardSessionsListUrl = (projectId: string, params?: WizardSessionsListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/wizard_sessions/?${stringifiedParams}`
        : `/api/projects/${projectId}/wizard_sessions/`
}

export const wizardSessionsList = async (
    projectId: string,
    params?: WizardSessionsListParams,
    options?: RequestInit
): Promise<PaginatedWizardSessionListApi> => {
    return apiMutator<PaginatedWizardSessionListApi>(getWizardSessionsListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getWizardSessionsCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/wizard_sessions/`
}

/**
 * Upsert a wizard session. The session_id key determines whether this creates a new row or replaces an existing one.
 */
export const wizardSessionsCreate = async (
    projectId: string,
    wizardSessionApi: NonReadonly<WizardSessionApi>,
    options?: RequestInit
): Promise<WizardSessionApi> => {
    return apiMutator<WizardSessionApi>(getWizardSessionsCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(wizardSessionApi),
    })
}

export const getWizardSessionsRetrieveUrl = (projectId: string, sessionId: string) => {
    return `/api/projects/${projectId}/wizard_sessions/${sessionId}/`
}

export const wizardSessionsRetrieve = async (
    projectId: string,
    sessionId: string,
    options?: RequestInit
): Promise<WizardSessionApi> => {
    return apiMutator<WizardSessionApi>(getWizardSessionsRetrieveUrl(projectId, sessionId), {
        ...options,
        method: 'GET',
    })
}

export const getWizardSessionsUpdateUrl = (projectId: string, sessionId: string) => {
    return `/api/projects/${projectId}/wizard_sessions/${sessionId}/`
}

export const wizardSessionsUpdate = async (
    projectId: string,
    sessionId: string,
    wizardSessionApi: NonReadonly<WizardSessionApi>,
    options?: RequestInit
): Promise<WizardSessionApi> => {
    return apiMutator<WizardSessionApi>(getWizardSessionsUpdateUrl(projectId, sessionId), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(wizardSessionApi),
    })
}

export const getWizardSessionsPartialUpdateUrl = (projectId: string, sessionId: string) => {
    return `/api/projects/${projectId}/wizard_sessions/${sessionId}/`
}

export const wizardSessionsPartialUpdate = async (
    projectId: string,
    sessionId: string,
    patchedWizardSessionApi?: NonReadonly<PatchedWizardSessionApi>,
    options?: RequestInit
): Promise<WizardSessionApi> => {
    return apiMutator<WizardSessionApi>(getWizardSessionsPartialUpdateUrl(projectId, sessionId), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedWizardSessionApi),
    })
}

export const getWizardSessionsDestroyUrl = (projectId: string, sessionId: string) => {
    return `/api/projects/${projectId}/wizard_sessions/${sessionId}/`
}

export const wizardSessionsDestroy = async (
    projectId: string,
    sessionId: string,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getWizardSessionsDestroyUrl(projectId, sessionId), {
        ...options,
        method: 'DELETE',
    })
}

export const getWizardListUrl = (params?: WizardListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0 ? `/api/wizard/?${stringifiedParams}` : `/api/wizard/`
}

export const wizardList = async (
    params?: WizardListParams,
    options?: RequestInit
): Promise<PaginatedWizardSessionListApi> => {
    return apiMutator<PaginatedWizardSessionListApi>(getWizardListUrl(params), {
        ...options,
        method: 'GET',
    })
}

export const getWizardCreateUrl = () => {
    return `/api/wizard/`
}

/**
 * Upsert a wizard session. The session_id key determines whether this creates a new row or replaces an existing one.
 */
export const wizardCreate = async (
    wizardSessionApi: NonReadonly<WizardSessionApi>,
    options?: RequestInit
): Promise<WizardSessionApi> => {
    return apiMutator<WizardSessionApi>(getWizardCreateUrl(), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(wizardSessionApi),
    })
}

export const getWizardRetrieveUrl = (sessionId: string) => {
    return `/api/wizard/${sessionId}/`
}

export const wizardRetrieve = async (sessionId: string, options?: RequestInit): Promise<WizardSessionApi> => {
    return apiMutator<WizardSessionApi>(getWizardRetrieveUrl(sessionId), {
        ...options,
        method: 'GET',
    })
}

export const getWizardUpdateUrl = (sessionId: string) => {
    return `/api/wizard/${sessionId}/`
}

export const wizardUpdate = async (
    sessionId: string,
    wizardSessionApi: NonReadonly<WizardSessionApi>,
    options?: RequestInit
): Promise<WizardSessionApi> => {
    return apiMutator<WizardSessionApi>(getWizardUpdateUrl(sessionId), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(wizardSessionApi),
    })
}

export const getWizardPartialUpdateUrl = (sessionId: string) => {
    return `/api/wizard/${sessionId}/`
}

export const wizardPartialUpdate = async (
    sessionId: string,
    patchedWizardSessionApi?: NonReadonly<PatchedWizardSessionApi>,
    options?: RequestInit
): Promise<WizardSessionApi> => {
    return apiMutator<WizardSessionApi>(getWizardPartialUpdateUrl(sessionId), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedWizardSessionApi),
    })
}

export const getWizardDestroyUrl = (sessionId: string) => {
    return `/api/wizard/${sessionId}/`
}

export const wizardDestroy = async (sessionId: string, options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getWizardDestroyUrl(sessionId), {
        ...options,
        method: 'DELETE',
    })
}
