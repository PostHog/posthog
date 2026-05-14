/**
 * Auto-generated from the Django backend OpenAPI schema.
 * To modify these types, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
export interface LiveDebuggerBreakpointApi {
    readonly id: string
    /** @nullable */
    repository?: string | null
    filename: string
    /**
     * @minimum 0
     * @maximum 2147483647
     */
    line_number: number
    enabled?: boolean
    /** @nullable */
    condition?: string | null
    readonly created_at: string
    readonly updated_at: string
}

export interface PaginatedLiveDebuggerBreakpointListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: LiveDebuggerBreakpointApi[]
}

export interface PatchedLiveDebuggerBreakpointApi {
    readonly id?: string
    /** @nullable */
    repository?: string | null
    filename?: string
    /**
     * @minimum 0
     * @maximum 2147483647
     */
    line_number?: number
    enabled?: boolean
    /** @nullable */
    condition?: string | null
    readonly created_at?: string
    readonly updated_at?: string
}

/**
 * Schema for a single active breakpoint
 */
export interface ActiveBreakpointApi {
    /** Unique identifier for the breakpoint */
    id: string
    /**
     * Repository identifier (e.g., 'PostHog/posthog')
     * @nullable
     */
    repository?: string | null
    /** File path where the breakpoint is set */
    filename: string
    /** Line number of the breakpoint */
    line_number: number
    /** Whether the breakpoint is enabled */
    enabled: boolean
    /**
     * Optional condition for the breakpoint
     * @nullable
     */
    condition?: string | null
}

/**
 * Response schema for active breakpoints endpoint
 */
export interface ActiveBreakpointsResponseApi {
    /** List of active breakpoints */
    breakpoints: ActiveBreakpointApi[]
}

/**
 * Local variables at the time of the hit
 */
export type BreakpointHitApiVariables = { [key: string]: unknown }

/**
 * Schema for a single breakpoint hit event
 */
export interface BreakpointHitApi {
    /** Unique identifier for the hit event */
    id: string
    /** Line number where the breakpoint was hit */
    lineNumber: number
    /** Name of the function where breakpoint was hit */
    functionName: string
    /** When the breakpoint was hit */
    timestamp: string
    /** Local variables at the time of the hit */
    variables: BreakpointHitApiVariables
    /** Stack trace at the time of the hit */
    stackTrace: unknown[]
    /** ID of the breakpoint that was hit */
    breakpoint_id: string
    /** Filename where the breakpoint was hit */
    filename: string
}

/**
 * Response schema for breakpoint hits endpoint
 */
export interface BreakpointHitsResponseApi {
    /** List of breakpoint hit events */
    results: BreakpointHitApi[]
    /** Number of results returned */
    count: number
    /** Whether there are more results available */
    has_more: boolean
}

/**
 * * `installed` - Installed
 * `uninstalled` - Uninstalled
 */
export type LiveDebuggerProgramStatusEnumApi =
    (typeof LiveDebuggerProgramStatusEnumApi)[keyof typeof LiveDebuggerProgramStatusEnumApi]

export const LiveDebuggerProgramStatusEnumApi = {
    Installed: 'installed',
    Uninstalled: 'uninstalled',
} as const

/**
 * Compact representation of a program for list views — omits the program code.
 */
export interface LiveDebuggerProgramListItemApi {
    /** Unique identifier for the program. */
    readonly id: string
    /** Human-readable description of the program. */
    readonly description: string
    /** Lifecycle status: 'installed' or 'uninstalled'.

  * `installed` - Installed
  * `uninstalled` - Uninstalled */
    readonly status: LiveDebuggerProgramStatusEnumApi
    /** Time the program was installed. */
    readonly created_at: string
    /** Time the program record was last modified. */
    readonly updated_at: string
}

export interface PaginatedLiveDebuggerProgramListItemListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: LiveDebuggerProgramListItemApi[]
}

/**
 * Full representation of a live debugger program, including its code.
 */
export interface LiveDebuggerProgramApi {
    readonly id: string
    /** The hogtrace program source code to install. This is executed by the client-side runtime to instrument production code with probes. */
    code: string
    /** Human-readable description of what this program does and why it was installed. */
    description?: string
    /** Lifecycle status of the program. 'installed' programs are active and will emit events when their probes are hit. 'uninstalled' programs are inactive and retained for history.

  * `installed` - Installed
  * `uninstalled` - Uninstalled */
    readonly status: LiveDebuggerProgramStatusEnumApi
    /** Time the program was installed. */
    readonly created_at: string
    /** Time the program record was last modified (e.g. on uninstall). */
    readonly updated_at: string
}

/**
 * Probe specification — at minimum `specifier` (e.g. `myapp.users.create_user`) and `target` (`entry`/`exit`).
 * @nullable
 */
export type ProgramEventApiProbeSpec = { [key: string]: unknown } | null

/**
 * User-named captures from the probe body, as a key/value map (whatever the program wrote in `capture(name=...)`).
 */
export type ProgramEventApiCaptures = { [key: string]: unknown }

/**
 * A single event emitted by a probe in a live debugger program.

Mirrors the property shape libdebugger emits for the `$hogtrace_capture`
event — see `libdebugger/instrumentation.py::_enqueue_message`.
 */
export interface ProgramEventApi {
    /** Unique identifier for this event. */
    id: string
    /** Wall-clock time at which the probe fired. */
    timestamp: string
    /** ID of the program that emitted this event. */
    program_id: string
    /**
     * Identifier of the specific probe within the program that fired (may be null).
     * @nullable
     */
    probe_id?: string | null
    /**
     * Probe specification — at minimum `specifier` (e.g. `myapp.users.create_user`) and `target` (`entry`/`exit`).
     * @nullable
     */
    probe_spec?: ProgramEventApiProbeSpec
    /** User-named captures from the probe body, as a key/value map (whatever the program wrote in `capture(name=...)`). */
    captures: ProgramEventApiCaptures
    /**
     * OS thread id of the request that hit the probe.
     * @nullable
     */
    thread_id?: number | null
    /**
     * Thread name of the request that hit the probe.
     * @nullable
     */
    thread_name?: string | null
}

/**
 * Paginated list of probe events for a single program.
 */
export interface ProgramEventsResponseApi {
    /** List of probe events, most recent first. */
    results: ProgramEventApi[]
    /** Number of events returned in this page. */
    count: number
    /** Whether additional events are available beyond this page. */
    has_more: boolean
}

/**
 * * `open` - Open
 * `closed` - Closed
 */
export type LiveDebuggerSessionStatusEnumApi =
    (typeof LiveDebuggerSessionStatusEnumApi)[keyof typeof LiveDebuggerSessionStatusEnumApi]

export const LiveDebuggerSessionStatusEnumApi = {
    Open: 'open',
    Closed: 'closed',
} as const

/**
 * Compact session for list views; omits entries.
 */
export interface LiveDebuggerSessionListItemApi {
    /** Unique identifier for the session. */
    readonly id: string
    /** Short human-readable name for the investigation. */
    readonly title: string
    /** What the agent is trying to figure out. */
    readonly description: string
    /** Lifecycle status: 'open' or 'closed'.

  * `open` - Open
  * `closed` - Closed */
    readonly status: LiveDebuggerSessionStatusEnumApi
    /** When the session was started. */
    readonly created_at: string
    /**
     * When the session was closed (null while open).
     * @nullable
     */
    readonly closed_at: string | null
}

export interface PaginatedLiveDebuggerSessionListItemListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: LiveDebuggerSessionListItemApi[]
}

/**
 * * `note` - Note
 * `program_install` - Program install
 * `program_uninstall` - Program uninstall
 * `event_highlight` - Event highlight
 * `conclusion` - Conclusion
 */
export type LiveDebuggerSessionEntryListItemKindEnumApi =
    (typeof LiveDebuggerSessionEntryListItemKindEnumApi)[keyof typeof LiveDebuggerSessionEntryListItemKindEnumApi]

export const LiveDebuggerSessionEntryListItemKindEnumApi = {
    Note: 'note',
    ProgramInstall: 'program_install',
    ProgramUninstall: 'program_uninstall',
    EventHighlight: 'event_highlight',
    Conclusion: 'conclusion',
} as const

/**
 * A single entry in a session's timeline.
 */
export interface LiveDebuggerSessionEntryListItemApi {
    /** Unique identifier for the entry. */
    readonly id: string
    /** Entry kind discriminator. One of: note, program_install, program_uninstall, event_highlight, conclusion.

  * `note` - Note
  * `program_install` - Program install
  * `program_uninstall` - Program uninstall
  * `event_highlight` - Event highlight
  * `conclusion` - Conclusion */
    readonly kind: LiveDebuggerSessionEntryListItemKindEnumApi
    /** Entry payload — shape depends on kind. note/conclusion: {markdown: str}. program_install/program_uninstall: {program_id: uuid}. event_highlight: {event_uuids: list[str], caption: str}. */
    readonly payload: unknown
    /** When the entry was appended. */
    readonly created_at: string
}

/**
 * Full session with its ordered entries timeline and the programs it owns.
 */
export interface LiveDebuggerSessionApi {
    readonly id: string
    /** Short human-readable name for the investigation. */
    title: string
    /** What the agent is trying to figure out. */
    description?: string
    /** Lifecycle status: 'open' or 'closed'.

  * `open` - Open
  * `closed` - Closed */
    readonly status: LiveDebuggerSessionStatusEnumApi
    /** When the session was started. */
    readonly created_at: string
    /**
     * When the session was closed (null while open).
     * @nullable
     */
    readonly closed_at: string | null
    readonly entries: readonly LiveDebuggerSessionEntryListItemApi[]
    readonly programs: readonly LiveDebuggerProgramApi[]
}

export interface CloseSessionRequestApi {
    /** Optional markdown summary. If provided, a `conclusion` entry is appended before the session is closed. */
    conclusion_markdown?: string
}

/**
 * Payload shape depends on kind. note/conclusion: {markdown: str}. event_highlight: {event_uuids: list[str], caption: str}.
 */
export type AddEntryRequestApiPayload = { [key: string]: unknown }

/**
 * * `note` - note
 * `event_highlight` - event_highlight
 * `conclusion` - conclusion
 */
export type AddEntryRequestKindEnumApi = (typeof AddEntryRequestKindEnumApi)[keyof typeof AddEntryRequestKindEnumApi]

export const AddEntryRequestKindEnumApi = {
    Note: 'note',
    EventHighlight: 'event_highlight',
    Conclusion: 'conclusion',
} as const

/**
 * Validates a direct-write session entry (note / event_highlight / conclusion).

`program_install` and `program_uninstall` entries are server-written side effects
of the install/uninstall endpoints and cannot be appended via this endpoint.
 */
export interface AddEntryRequestApi {
    /** Entry kind: note, event_highlight, or conclusion.

  * `note` - note
  * `event_highlight` - event_highlight
  * `conclusion` - conclusion */
    kind: AddEntryRequestKindEnumApi
    /** Payload shape depends on kind. note/conclusion: {markdown: str}. event_highlight: {event_uuids: list[str], caption: str}. */
    payload: AddEntryRequestApiPayload
}

export interface InstallProgramInSessionRequestApi {
    /** The hogtrace program source code to install. */
    code: string
    /** Human-readable description of what this program observes and why. */
    description?: string
}

export interface UninstallProgramInSessionRequestApi {
    /** ID of the program to uninstall. */
    program_id: string
}

export type LiveDebuggerBreakpointsListParams = {
    filename?: string
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
    repository?: string
}

export type LiveDebuggerBreakpointsActiveRetrieveParams = {
    /**
     * Only return enabled breakpoints
     */
    enabled?: boolean
    /**
     * Filter breakpoints for a specific file
     */
    filename?: string
    /**
     * Filter breakpoints for a specific repository (e.g., 'PostHog/posthog')
     */
    repository?: string
}

export type LiveDebuggerBreakpointsBreakpointHitsRetrieveParams = {
    /**
     * Filter hits for specific breakpoints (repeat parameter for multiple IDs, e.g., ?breakpoint_ids=uuid1&breakpoint_ids=uuid2)
     */
    breakpoint_ids?: string
    /**
     * Number of hits to return (default: 100, max: 1000)
     */
    limit?: number
    /**
     * Pagination offset for retrieving additional results (default: 0)
     */
    offset?: number
}

export type LiveDebuggerProgramsListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}

export type LiveDebuggerProgramsEventsRetrieveParams = {
    /**
     * Maximum number of events to return (default 100, max 1000).
     */
    limit?: number
    /**
     * Pagination offset.
     */
    offset?: number
}

export type LiveDebuggerSessionsListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}

export type LiveDebuggerSessionsProgramEventsRetrieveParams = {
    /**
     * Maximum number of events to return (default 100, max 1000).
     */
    limit?: number
    /**
     * Pagination offset.
     */
    offset?: number
    /**
     * ID of the program (must belong to this session).
     */
    program_id: string
}
