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
    MeepContextAddApi,
    MeepContextApi,
    MeepConversationBindingApi,
    MeepRoutineApi,
    MeepRoutineBindApi,
    MeepScoutApi,
    MeepScoutCreateApi,
    MeepScoutStatusApi,
    MeepTaskAnswerApi,
    MeepTaskStartApi,
    MeepTaskStartResultApi,
    MeepTaskWaitApi,
    MeepTaskWaitResultApi,
    MeepTopicApi,
    MeepTopicDetailsApi,
    MeepTopicsListParams,
    PaginatedMeepTopicListApi,
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

export const getMeepTopicsListUrl = (projectId: string, params?: MeepTopicsListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/meep/topics/?${stringifiedParams}`
        : `/api/projects/${projectId}/meep/topics/`
}

export const meepTopicsList = async (
    projectId: string,
    params?: MeepTopicsListParams,
    options?: RequestInit
): Promise<PaginatedMeepTopicListApi> => {
    return apiMutator<PaginatedMeepTopicListApi>(getMeepTopicsListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getMeepTopicsCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/meep/topics/`
}

export const meepTopicsCreate = async (
    projectId: string,
    meepTopicApi: NonReadonly<MeepTopicApi>,
    options?: RequestInit
): Promise<MeepTopicApi> => {
    return apiMutator<MeepTopicApi>(getMeepTopicsCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(meepTopicApi),
    })
}

export const getMeepTopicsRetrieveUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/meep/topics/${id}/`
}

export const meepTopicsRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<MeepTopicDetailsApi> => {
    return apiMutator<MeepTopicDetailsApi>(getMeepTopicsRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getMeepTopicsAddContextUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/meep/topics/${id}/context/`
}

export const meepTopicsAddContext = async (
    projectId: string,
    id: string,
    meepContextAddApi: MeepContextAddApi,
    options?: RequestInit
): Promise<MeepContextApi> => {
    return apiMutator<MeepContextApi>(getMeepTopicsAddContextUrl(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(meepContextAddApi),
    })
}

export const getMeepTopicsConversationCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/meep/topics/${id}/conversation/`
}

export const meepTopicsConversationCreate = async (
    projectId: string,
    id: string,
    meepConversationBindingApi: MeepConversationBindingApi,
    options?: RequestInit
): Promise<MeepTopicApi> => {
    return apiMutator<MeepTopicApi>(getMeepTopicsConversationCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(meepConversationBindingApi),
    })
}

export const getMeepTopicsBindRoutineUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/meep/topics/${id}/routines/`
}

export const meepTopicsBindRoutine = async (
    projectId: string,
    id: string,
    meepRoutineBindApi: MeepRoutineBindApi,
    options?: RequestInit
): Promise<MeepRoutineApi> => {
    return apiMutator<MeepRoutineApi>(getMeepTopicsBindRoutineUrl(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(meepRoutineBindApi),
    })
}

export const getMeepTopicsSetScoutEnabledUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/meep/topics/${id}/scout_status/`
}

export const meepTopicsSetScoutEnabled = async (
    projectId: string,
    id: string,
    meepScoutStatusApi: MeepScoutStatusApi,
    options?: RequestInit
): Promise<MeepScoutApi> => {
    return apiMutator<MeepScoutApi>(getMeepTopicsSetScoutEnabledUrl(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(meepScoutStatusApi),
    })
}

export const getMeepTopicsCreateScoutUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/meep/topics/${id}/scouts/`
}

export const meepTopicsCreateScout = async (
    projectId: string,
    id: string,
    meepScoutCreateApi: MeepScoutCreateApi,
    options?: RequestInit
): Promise<MeepScoutApi> => {
    return apiMutator<MeepScoutApi>(getMeepTopicsCreateScoutUrl(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(meepScoutCreateApi),
    })
}

export const getMeepTopicsAnswerTaskUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/meep/topics/${id}/tasks/answer/`
}

export const meepTopicsAnswerTask = async (
    projectId: string,
    id: string,
    meepTaskAnswerApi: MeepTaskAnswerApi,
    options?: RequestInit
): Promise<MeepTaskStartResultApi> => {
    return apiMutator<MeepTaskStartResultApi>(getMeepTopicsAnswerTaskUrl(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(meepTaskAnswerApi),
    })
}

export const getMeepTopicsStartTaskUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/meep/topics/${id}/tasks/start/`
}

export const meepTopicsStartTask = async (
    projectId: string,
    id: string,
    meepTaskStartApi: MeepTaskStartApi,
    options?: RequestInit
): Promise<MeepTaskStartResultApi> => {
    return apiMutator<MeepTaskStartResultApi>(getMeepTopicsStartTaskUrl(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(meepTaskStartApi),
    })
}

export const getMeepTopicsWaitTasksUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/meep/topics/${id}/tasks/wait/`
}

export const meepTopicsWaitTasks = async (
    projectId: string,
    id: string,
    meepTaskWaitApi: MeepTaskWaitApi,
    options?: RequestInit
): Promise<MeepTaskWaitResultApi> => {
    return apiMutator<MeepTaskWaitResultApi>(getMeepTopicsWaitTasksUrl(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(meepTaskWaitApi),
    })
}
