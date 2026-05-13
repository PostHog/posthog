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
    ActiveBreakpointsResponseApi,
    BreakpointHitsResponseApi,
    LiveDebuggerBreakpointApi,
    LiveDebuggerBreakpointsActiveRetrieveParams,
    LiveDebuggerBreakpointsBreakpointHitsRetrieveParams,
    LiveDebuggerBreakpointsListParams,
    LiveDebuggerProgramApi,
    LiveDebuggerProgramsListParams,
    PaginatedLiveDebuggerBreakpointListApi,
    PaginatedLiveDebuggerProgramListItemListApi,
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

export const getLiveDebuggerProgramsActiveRetrieveUrl = (projectId: string) => {
    return `/api/projects/${projectId}/live_debugger/programs/active/`
}

/**
 * External API endpoint for the libdebugger runtime poller. Returns the team's installed hogtrace programs as a single `ProgramList` protobuf payload (see hogtrace/proto/bytecode.proto). The poller diffs against its installed set using `Program.hash` to decide install/uninstall/update.

Authentication: personal API key in the Authorization header: `Authorization: Bearer phx_<your-personal-api-key>`. Required scope: `live_debugger:read`.
 * @summary Get compiled active programs (External API)
 */
export const liveDebuggerProgramsActiveRetrieve = async (projectId: string, options?: RequestInit): Promise<Blob> => {
    return apiMutator<Blob>(getLiveDebuggerProgramsActiveRetrieveUrl(projectId), {
        ...options,
        method: 'GET',
    })
}

export const getLiveDebuggerBreakpointsListUrl = (projectId: string, params?: LiveDebuggerBreakpointsListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/live_debugger_breakpoints/?${stringifiedParams}`
        : `/api/projects/${projectId}/live_debugger_breakpoints/`
}

/**
 * Create, Read, Update and Delete breakpoints for live debugging.
 */
export const liveDebuggerBreakpointsList = async (
    projectId: string,
    params?: LiveDebuggerBreakpointsListParams,
    options?: RequestInit
): Promise<PaginatedLiveDebuggerBreakpointListApi> => {
    return apiMutator<PaginatedLiveDebuggerBreakpointListApi>(getLiveDebuggerBreakpointsListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getLiveDebuggerBreakpointsCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/live_debugger_breakpoints/`
}

/**
 * Create, Read, Update and Delete breakpoints for live debugging.
 */
export const liveDebuggerBreakpointsCreate = async (
    projectId: string,
    liveDebuggerBreakpointApi: NonReadonly<LiveDebuggerBreakpointApi>,
    options?: RequestInit
): Promise<LiveDebuggerBreakpointApi> => {
    return apiMutator<LiveDebuggerBreakpointApi>(getLiveDebuggerBreakpointsCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(liveDebuggerBreakpointApi),
    })
}

export const getLiveDebuggerBreakpointsActiveRetrieveUrl = (
    projectId: string,
    params?: LiveDebuggerBreakpointsActiveRetrieveParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/live_debugger_breakpoints/active/?${stringifiedParams}`
        : `/api/projects/${projectId}/live_debugger_breakpoints/active/`
}

/**
 * External API endpoint for client applications to fetch active breakpoints using Project API key. This endpoint allows external client applications (like Python scripts, Node.js apps, etc.) to fetch the list of active breakpoints so they can instrument their code accordingly.

Authentication: Requires a Project API Key in the Authorization header: `Authorization: Bearer phs_<your-project-api-key>`. You can find your Project API Key in PostHog at: Settings → Project → Project API Key
 * @summary Get active breakpoints (External API)
 */
export const liveDebuggerBreakpointsActiveRetrieve = async (
    projectId: string,
    params?: LiveDebuggerBreakpointsActiveRetrieveParams,
    options?: RequestInit
): Promise<ActiveBreakpointsResponseApi> => {
    return apiMutator<ActiveBreakpointsResponseApi>(getLiveDebuggerBreakpointsActiveRetrieveUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getLiveDebuggerBreakpointsBreakpointHitsRetrieveUrl = (
    projectId: string,
    params?: LiveDebuggerBreakpointsBreakpointHitsRetrieveParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/live_debugger_breakpoints/breakpoint_hits/?${stringifiedParams}`
        : `/api/projects/${projectId}/live_debugger_breakpoints/breakpoint_hits/`
}

/**
 * Retrieve breakpoint hit events from ClickHouse with optional filtering and pagination. Returns hit events containing stack traces, local variables, and execution context from your application's runtime.

Security: Breakpoint IDs are filtered to only include those belonging to the current team.
 * @summary Get breakpoint hits
 */
export const liveDebuggerBreakpointsBreakpointHitsRetrieve = async (
    projectId: string,
    params?: LiveDebuggerBreakpointsBreakpointHitsRetrieveParams,
    options?: RequestInit
): Promise<BreakpointHitsResponseApi> => {
    return apiMutator<BreakpointHitsResponseApi>(
        getLiveDebuggerBreakpointsBreakpointHitsRetrieveUrl(projectId, params),
        {
            ...options,
            method: 'GET',
        }
    )
}

export const getLiveDebuggerProgramsListUrl = (projectId: string, params?: LiveDebuggerProgramsListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/live_debugger_programs/?${stringifiedParams}`
        : `/api/projects/${projectId}/live_debugger_programs/`
}

/**
 * List programs for the current team, most recently installed first. Omits program code.
 * @summary List live debugger programs
 */
export const liveDebuggerProgramsList = async (
    projectId: string,
    params?: LiveDebuggerProgramsListParams,
    options?: RequestInit
): Promise<PaginatedLiveDebuggerProgramListItemListApi> => {
    return apiMutator<PaginatedLiveDebuggerProgramListItemListApi>(getLiveDebuggerProgramsListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getLiveDebuggerProgramsCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/live_debugger_programs/`
}

/**
 * Install a hogtrace program. The program will be picked up by the client-side runtime and its probes will start emitting events on hit. Returns the full program record including its newly assigned id.
 * @summary Install a live debugger program
 */
export const liveDebuggerProgramsCreate = async (
    projectId: string,
    liveDebuggerProgramApi: NonReadonly<LiveDebuggerProgramApi>,
    options?: RequestInit
): Promise<LiveDebuggerProgramApi> => {
    return apiMutator<LiveDebuggerProgramApi>(getLiveDebuggerProgramsCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(liveDebuggerProgramApi),
    })
}
