/**
 * Auto-generated Zod validation schemas from the Django backend OpenAPI schema.
 * To modify these schemas, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
import * as zod from 'zod'

/**
 * Create, Read, Update and Delete breakpoints for live debugging.
 */
export const liveDebuggerBreakpointsCreateBodyLineNumberMin = 0
export const liveDebuggerBreakpointsCreateBodyLineNumberMax = 2147483647

export const LiveDebuggerBreakpointsCreateBody = /* @__PURE__ */ zod.object({
    repository: zod.string().nullish(),
    filename: zod.string(),
    line_number: zod
        .number()
        .min(liveDebuggerBreakpointsCreateBodyLineNumberMin)
        .max(liveDebuggerBreakpointsCreateBodyLineNumberMax),
    enabled: zod.boolean().optional(),
    condition: zod.string().nullish(),
})

/**
 * Create, Read, Update and Delete breakpoints for live debugging.
 */
export const liveDebuggerBreakpointsUpdateBodyLineNumberMin = 0
export const liveDebuggerBreakpointsUpdateBodyLineNumberMax = 2147483647

export const LiveDebuggerBreakpointsUpdateBody = /* @__PURE__ */ zod.object({
    repository: zod.string().nullish(),
    filename: zod.string(),
    line_number: zod
        .number()
        .min(liveDebuggerBreakpointsUpdateBodyLineNumberMin)
        .max(liveDebuggerBreakpointsUpdateBodyLineNumberMax),
    enabled: zod.boolean().optional(),
    condition: zod.string().nullish(),
})

/**
 * Create, Read, Update and Delete breakpoints for live debugging.
 */
export const liveDebuggerBreakpointsPartialUpdateBodyLineNumberMin = 0
export const liveDebuggerBreakpointsPartialUpdateBodyLineNumberMax = 2147483647

export const LiveDebuggerBreakpointsPartialUpdateBody = /* @__PURE__ */ zod.object({
    repository: zod.string().nullish(),
    filename: zod.string().optional(),
    line_number: zod
        .number()
        .min(liveDebuggerBreakpointsPartialUpdateBodyLineNumberMin)
        .max(liveDebuggerBreakpointsPartialUpdateBodyLineNumberMax)
        .optional(),
    enabled: zod.boolean().optional(),
    condition: zod.string().nullish(),
})

/**
 * Install a hogtrace program. The program will be picked up by the client-side runtime and its probes will start emitting events on hit. Returns the full program record including its newly assigned id.
 * @summary Install a live debugger program
 */
export const LiveDebuggerProgramsCreateBody = /* @__PURE__ */ zod
    .object({
        code: zod
            .string()
            .describe(
                'The hogtrace program source code to install. This is executed by the client-side runtime to instrument production code with probes.'
            ),
        description: zod
            .string()
            .optional()
            .describe('Human-readable description of what this program does and why it was installed.'),
    })
    .describe('Full representation of a live debugger program, including its code.')

/**
 * Start, list, inspect, and close debugging sessions.

A session is the agent's investigation envelope. Every program install/uninstall,
note, event highlight, and conclusion is appended to the session's timeline,
producing a human-readable record of what the agent tried and what it learned.
 * @summary Start a debugging session
 */
export const LiveDebuggerSessionsCreateBody = /* @__PURE__ */ zod
    .object({
        title: zod.string().describe('Short human-readable name for the investigation.'),
        description: zod.string().optional().describe('What the agent is trying to figure out.'),
    })
    .describe('Full session with its ordered entries timeline and the programs it owns.')

/**
 * Atomically transitions the session to `closed`, sets `closed_at`, optionally appends a `conclusion` entry, and auto-uninstalls every program that still has `installed` status in this session. Idempotent: closing an already-closed session returns the session unchanged.
 * @summary Close a debugging session
 */
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
export const LiveDebuggerSessionsEntriesCreateBody = /* @__PURE__ */ zod
    .object({
        kind: zod
            .enum(['note', 'event_highlight', 'conclusion'])
            .describe('\* `note` - note\n\* `event_highlight` - event_highlight\n\* `conclusion` - conclusion')
            .describe(
                'Entry kind: note, event_highlight, or conclusion.\n\n\* `note` - note\n\* `event_highlight` - event_highlight\n\* `conclusion` - conclusion'
            ),
        payload: zod
            .record(zod.string(), zod.unknown())
            .describe(
                'Payload shape depends on kind. note\/conclusion: {markdown: str}. event_highlight: {event_uuids: list[str], caption: str}.'
            ),
    })
    .describe(
        'Validates a direct-write session entry (note \/ event_highlight \/ conclusion).\n\n`program_install` and `program_uninstall` entries are server-written side effects\nof the install\/uninstall endpoints and cannot be appended via this endpoint.'
    )

/**
 * Atomically installs a hogtrace program scoped to this session and appends a `program_install` entry to the timeline. Returns the installed program.
 * @summary Install a hogtrace program inside a session
 */
export const liveDebuggerSessionsInstallProgramCreateBodyDescriptionDefault = ``

export const LiveDebuggerSessionsInstallProgramCreateBody = /* @__PURE__ */ zod.object({
    code: zod.string().describe('The hogtrace program source code to install.'),
    description: zod
        .string()
        .default(liveDebuggerSessionsInstallProgramCreateBodyDescriptionDefault)
        .describe('Human-readable description of what this program observes and why.'),
})

/**
 * Soft-uninstalls a program belonging to this session and appends a `program_uninstall` entry. Already-uninstalled programs are no-ops. Calling this on a program that does not belong to this session returns 404.
 * @summary Uninstall a program from a session
 */
export const LiveDebuggerSessionsUninstallProgramCreateBody = /* @__PURE__ */ zod.object({
    program_id: zod.uuid().describe('ID of the program to uninstall.'),
})
