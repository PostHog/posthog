/**
 * Auto-generated from the Django backend OpenAPI schema.
 * MCP service uses these Zod schemas for generated tool handlers.
 * To regenerate: hogli build:openapi
 *
 * PostHog API - MCP 8 enabled ops
 * OpenAPI spec version: 1.0.0
 */
import * as zod from 'zod'

/**
 * List sessions for the current project, most recently started first.
 * @summary List debugging sessions
 */
export const LiveDebuggerSessionsListParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const LiveDebuggerSessionsListQueryParams = /* @__PURE__ */ zod.object({
    limit: zod.number().optional().describe('Number of results to return per page.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
})

/**
 * Start, list, inspect, and close debugging sessions.

A session is the agent's investigation envelope. Every program install/uninstall,
note, event highlight, and conclusion is appended to the session's timeline,
producing a human-readable record of what the agent tried and what it learned.
 * @summary Start a debugging session
 */
export const LiveDebuggerSessionsCreateParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const LiveDebuggerSessionsCreateBody = /* @__PURE__ */ zod
    .object({
        title: zod.string().describe('Short human-readable name for the investigation.'),
        description: zod.string().optional().describe('What the agent is trying to figure out.'),
    })
    .describe('Full session with its ordered entries timeline and the programs it owns.')

/**
 * Retrieve a single session with its full ordered entries timeline.
 * @summary Show a debugging session
 */
export const LiveDebuggerSessionsRetrieveParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this live debugger session.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

/**
 * Atomically transitions the session to `closed`, sets `closed_at`, optionally appends a `conclusion` entry, and auto-uninstalls every program that still has `installed` status in this session. Idempotent: closing an already-closed session returns the session unchanged.
 * @summary Close a debugging session
 */
export const LiveDebuggerSessionsCloseCreateParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this live debugger session.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const LiveDebuggerSessionsCloseCreateBody = /* @__PURE__ */ zod.object({
    conclusion_markdown: zod
        .string()
        .optional()
        .describe(
            'Optional markdown summary. If provided, a `conclusion` entry is appended before the session is closed.'
        ),
})

/**
 * Appends a direct-write entry to the session's timeline. Use `kind` to select between `note`, `event_highlight`, and `conclusion`. `program_install` and `program_uninstall` entries are produced as side effects of the install/uninstall endpoints and cannot be added directly.
 * @summary Append a note, event highlight, or conclusion entry
 */
export const LiveDebuggerSessionsEntriesCreateParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this live debugger session.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const LiveDebuggerSessionsEntriesCreateBody = /* @__PURE__ */ zod
    .object({
        kind: zod
            .enum(['note', 'event_highlight', 'conclusion'])
            .describe('* `note` - note\n* `event_highlight` - event_highlight\n* `conclusion` - conclusion')
            .describe(
                'Entry kind: note, event_highlight, or conclusion.\n\n* `note` - note\n* `event_highlight` - event_highlight\n* `conclusion` - conclusion'
            ),
        payload: zod
            .record(zod.string(), zod.unknown())
            .describe(
                'Payload shape depends on kind. note/conclusion: {markdown: str}. event_highlight: {event_uuids: list[str], caption: str}.'
            ),
    })
    .describe(
        'Validates a direct-write session entry (note / event_highlight / conclusion).\n\n`program_install` and `program_uninstall` entries are server-written side effects\nof the install/uninstall endpoints and cannot be appended via this endpoint.'
    )

/**
 * Atomically installs a hogtrace program scoped to this session and appends a `program_install` entry to the timeline. Returns the installed program.
 * @summary Install a hogtrace program inside a session
 */
export const LiveDebuggerSessionsInstallProgramCreateParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this live debugger session.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const liveDebuggerSessionsInstallProgramCreateBodyDescriptionDefault = ``

export const LiveDebuggerSessionsInstallProgramCreateBody = /* @__PURE__ */ zod.object({
    code: zod.string().describe('The hogtrace program source code to install.'),
    description: zod
        .string()
        .default(liveDebuggerSessionsInstallProgramCreateBodyDescriptionDefault)
        .describe('Human-readable description of what this program observes and why.'),
})

/**
 * Retrieves probe-hit events emitted by the given program. The program must belong to this session; otherwise 404 is returned. Returns events newest first.
 * @summary Get probe events for a program in a session
 */
export const LiveDebuggerSessionsProgramEventsRetrieveParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this live debugger session.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const LiveDebuggerSessionsProgramEventsRetrieveQueryParams = /* @__PURE__ */ zod.object({
    limit: zod.number().optional().describe('Maximum number of events to return (default 100, max 1000).'),
    offset: zod.number().optional().describe('Pagination offset.'),
    program_id: zod.string().describe('ID of the program (must belong to this session).'),
})

/**
 * Soft-uninstalls a program belonging to this session and appends a `program_uninstall` entry. Already-uninstalled programs are no-ops. Calling this on a program that does not belong to this session returns 404.
 * @summary Uninstall a program from a session
 */
export const LiveDebuggerSessionsUninstallProgramCreateParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this live debugger session.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const LiveDebuggerSessionsUninstallProgramCreateBody = /* @__PURE__ */ zod.object({
    program_id: zod.string().describe('ID of the program to uninstall.'),
})
