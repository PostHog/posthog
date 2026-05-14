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
    AddEntryRequestApi,
    BreakpointHitsResponseApi,
    CloseSessionRequestApi,
    InstallProgramInSessionRequestApi,
    LiveDebuggerBreakpointApi,
    LiveDebuggerBreakpointsActiveRetrieveParams,
    LiveDebuggerBreakpointsBreakpointHitsRetrieveParams,
    LiveDebuggerBreakpointsListParams,
    LiveDebuggerProgramApi,
    LiveDebuggerProgramsEventsRetrieveParams,
    LiveDebuggerProgramsListParams,
    LiveDebuggerSessionApi,
    LiveDebuggerSessionEntryListItemApi,
    LiveDebuggerSessionsListParams,
    LiveDebuggerSessionsProgramEventsRetrieveParams,
    PaginatedLiveDebuggerBreakpointListApi,
    PaginatedLiveDebuggerProgramListItemListApi,
    PaginatedLiveDebuggerSessionListItemListApi,
    PatchedLiveDebuggerBreakpointApi,
    ProgramEventsResponseApi,
    UninstallProgramInSessionRequestApi,
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

export const getLiveDebuggerBreakpointsRetrieveUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/live_debugger_breakpoints/${id}/`
}

/**
 * Create, Read, Update and Delete breakpoints for live debugging.
 */
export const liveDebuggerBreakpointsRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<LiveDebuggerBreakpointApi> => {
    return apiMutator<LiveDebuggerBreakpointApi>(getLiveDebuggerBreakpointsRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getLiveDebuggerBreakpointsUpdateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/live_debugger_breakpoints/${id}/`
}

/**
 * Create, Read, Update and Delete breakpoints for live debugging.
 */
export const liveDebuggerBreakpointsUpdate = async (
    projectId: string,
    id: string,
    liveDebuggerBreakpointApi: NonReadonly<LiveDebuggerBreakpointApi>,
    options?: RequestInit
): Promise<LiveDebuggerBreakpointApi> => {
    return apiMutator<LiveDebuggerBreakpointApi>(getLiveDebuggerBreakpointsUpdateUrl(projectId, id), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(liveDebuggerBreakpointApi),
    })
}

export const getLiveDebuggerBreakpointsPartialUpdateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/live_debugger_breakpoints/${id}/`
}

/**
 * Create, Read, Update and Delete breakpoints for live debugging.
 */
export const liveDebuggerBreakpointsPartialUpdate = async (
    projectId: string,
    id: string,
    patchedLiveDebuggerBreakpointApi?: NonReadonly<PatchedLiveDebuggerBreakpointApi>,
    options?: RequestInit
): Promise<LiveDebuggerBreakpointApi> => {
    return apiMutator<LiveDebuggerBreakpointApi>(getLiveDebuggerBreakpointsPartialUpdateUrl(projectId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedLiveDebuggerBreakpointApi),
    })
}

export const getLiveDebuggerBreakpointsDestroyUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/live_debugger_breakpoints/${id}/`
}

/**
 * Create, Read, Update and Delete breakpoints for live debugging.
 */
export const liveDebuggerBreakpointsDestroy = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getLiveDebuggerBreakpointsDestroyUrl(projectId, id), {
        ...options,
        method: 'DELETE',
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

export const getLiveDebuggerProgramsRetrieveUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/live_debugger_programs/${id}/`
}

/**
 * Retrieve a single program by id, including its full hogtrace program source code.
 * @summary Show a live debugger program
 */
export const liveDebuggerProgramsRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<LiveDebuggerProgramApi> => {
    return apiMutator<LiveDebuggerProgramApi>(getLiveDebuggerProgramsRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getLiveDebuggerProgramsEventsRetrieveUrl = (
    projectId: string,
    id: string,
    params?: LiveDebuggerProgramsEventsRetrieveParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/live_debugger_programs/${id}/events/?${stringifiedParams}`
        : `/api/projects/${projectId}/live_debugger_programs/${id}/events/`
}

/**
 * Retrieve probe-hit events emitted by this program from ClickHouse. Events are filtered by the program id stored in the `$program_id` property and returned most recent first.
 * @summary Get events emitted by a program
 */
export const liveDebuggerProgramsEventsRetrieve = async (
    projectId: string,
    id: string,
    params?: LiveDebuggerProgramsEventsRetrieveParams,
    options?: RequestInit
): Promise<ProgramEventsResponseApi> => {
    return apiMutator<ProgramEventsResponseApi>(getLiveDebuggerProgramsEventsRetrieveUrl(projectId, id, params), {
        ...options,
        method: 'GET',
    })
}

export const getLiveDebuggerProgramsUninstallCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/live_debugger_programs/${id}/uninstall/`
}

/**
 * Soft-uninstall a program by transitioning its status to 'uninstalled'. The program record and any events it previously emitted remain queryable. Returns the updated program.
 * @summary Uninstall a live debugger program
 */
export const liveDebuggerProgramsUninstallCreate = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<LiveDebuggerProgramApi> => {
    return apiMutator<LiveDebuggerProgramApi>(getLiveDebuggerProgramsUninstallCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
    })
}

export const getLiveDebuggerSessionsListUrl = (projectId: string, params?: LiveDebuggerSessionsListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/live_debugger_sessions/?${stringifiedParams}`
        : `/api/projects/${projectId}/live_debugger_sessions/`
}

/**
 * List sessions for the current project, most recently started first.
 * @summary List debugging sessions
 */
export const liveDebuggerSessionsList = async (
    projectId: string,
    params?: LiveDebuggerSessionsListParams,
    options?: RequestInit
): Promise<PaginatedLiveDebuggerSessionListItemListApi> => {
    return apiMutator<PaginatedLiveDebuggerSessionListItemListApi>(getLiveDebuggerSessionsListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getLiveDebuggerSessionsCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/live_debugger_sessions/`
}

/**
 * Start, list, inspect, and close debugging sessions.

A session is the agent's investigation envelope. Every program install/uninstall,
note, event highlight, and conclusion is appended to the session's timeline,
producing a human-readable record of what the agent tried and what it learned.
 * @summary Start a debugging session
 */
export const liveDebuggerSessionsCreate = async (
    projectId: string,
    liveDebuggerSessionApi: NonReadonly<LiveDebuggerSessionApi>,
    options?: RequestInit
): Promise<LiveDebuggerSessionApi> => {
    return apiMutator<LiveDebuggerSessionApi>(getLiveDebuggerSessionsCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(liveDebuggerSessionApi),
    })
}

export const getLiveDebuggerSessionsRetrieveUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/live_debugger_sessions/${id}/`
}

/**
 * Retrieve a single session with its full ordered entries timeline.
 * @summary Show a debugging session
 */
export const liveDebuggerSessionsRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<LiveDebuggerSessionApi> => {
    return apiMutator<LiveDebuggerSessionApi>(getLiveDebuggerSessionsRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getLiveDebuggerSessionsCloseCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/live_debugger_sessions/${id}/close/`
}

/**
 * Atomically transitions the session to `closed`, sets `closed_at`, optionally appends a `conclusion` entry, and auto-uninstalls every program that still has `installed` status in this session. Idempotent: closing an already-closed session returns the session unchanged.
 * @summary Close a debugging session
 */
export const liveDebuggerSessionsCloseCreate = async (
    projectId: string,
    id: string,
    closeSessionRequestApi?: CloseSessionRequestApi,
    options?: RequestInit
): Promise<LiveDebuggerSessionApi> => {
    return apiMutator<LiveDebuggerSessionApi>(getLiveDebuggerSessionsCloseCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(closeSessionRequestApi),
    })
}

export const getLiveDebuggerSessionsEntriesCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/live_debugger_sessions/${id}/entries/`
}

/**
 * Appends a direct-write entry to the session's timeline. Use `kind` to select between `note`, `event_highlight`, and `conclusion`. `program_install` and `program_uninstall` entries are produced as side effects of the install/uninstall endpoints and cannot be added directly.
 * @summary Append a note, event highlight, or conclusion entry
 */
export const liveDebuggerSessionsEntriesCreate = async (
    projectId: string,
    id: string,
    addEntryRequestApi: AddEntryRequestApi,
    options?: RequestInit
): Promise<LiveDebuggerSessionEntryListItemApi> => {
    return apiMutator<LiveDebuggerSessionEntryListItemApi>(getLiveDebuggerSessionsEntriesCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(addEntryRequestApi),
    })
}

export const getLiveDebuggerSessionsInstallProgramCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/live_debugger_sessions/${id}/install_program/`
}

/**
 * Atomically installs a hogtrace program scoped to this session and appends a `program_install` entry to the timeline. Returns the installed program.
 * @summary Install a hogtrace program inside a session
 */
export const liveDebuggerSessionsInstallProgramCreate = async (
    projectId: string,
    id: string,
    installProgramInSessionRequestApi: InstallProgramInSessionRequestApi,
    options?: RequestInit
): Promise<LiveDebuggerProgramApi> => {
    return apiMutator<LiveDebuggerProgramApi>(getLiveDebuggerSessionsInstallProgramCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(installProgramInSessionRequestApi),
    })
}

export const getLiveDebuggerSessionsProgramEventsRetrieveUrl = (
    projectId: string,
    id: string,
    params: LiveDebuggerSessionsProgramEventsRetrieveParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/live_debugger_sessions/${id}/program_events/?${stringifiedParams}`
        : `/api/projects/${projectId}/live_debugger_sessions/${id}/program_events/`
}

/**
 * Retrieves probe-hit events emitted by the given program. The program must belong to this session; otherwise 404 is returned. Returns events newest first.
 * @summary Get probe events for a program in a session
 */
export const liveDebuggerSessionsProgramEventsRetrieve = async (
    projectId: string,
    id: string,
    params: LiveDebuggerSessionsProgramEventsRetrieveParams,
    options?: RequestInit
): Promise<ProgramEventsResponseApi> => {
    return apiMutator<ProgramEventsResponseApi>(
        getLiveDebuggerSessionsProgramEventsRetrieveUrl(projectId, id, params),
        {
            ...options,
            method: 'GET',
        }
    )
}

export const getLiveDebuggerSessionsUninstallProgramCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/live_debugger_sessions/${id}/uninstall_program/`
}

/**
 * Soft-uninstalls a program belonging to this session and appends a `program_uninstall` entry. Already-uninstalled programs are no-ops. Calling this on a program that does not belong to this session returns 404.
 * @summary Uninstall a program from a session
 */
export const liveDebuggerSessionsUninstallProgramCreate = async (
    projectId: string,
    id: string,
    uninstallProgramInSessionRequestApi: UninstallProgramInSessionRequestApi,
    options?: RequestInit
): Promise<LiveDebuggerProgramApi> => {
    return apiMutator<LiveDebuggerProgramApi>(getLiveDebuggerSessionsUninstallProgramCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(uninstallProgramInSessionRequestApi),
    })
}
