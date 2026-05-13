/**
 * Auto-generated from the Django backend OpenAPI schema.
 * MCP service uses these Zod schemas for generated tool handlers.
 * To regenerate: hogli build:openapi
 *
 * PostHog API - MCP 5 enabled ops
 * OpenAPI spec version: 1.0.0
 */
import * as zod from 'zod'

/**
 * List programs for the current team, most recently installed first. Omits program code.
 * @summary List live debugger programs
 */
export const LiveDebuggerProgramsListParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const LiveDebuggerProgramsListQueryParams = /* @__PURE__ */ zod.object({
    limit: zod.number().optional().describe('Number of results to return per page.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
})

/**
 * Install a hogtrace program. The program will be picked up by the client-side runtime and its probes will start emitting events on hit. Returns the full program record including its newly assigned id.
 * @summary Install a live debugger program
 */
export const LiveDebuggerProgramsCreateParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

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
 * Retrieve a single program by id, including its full hogtrace program source code.
 * @summary Show a live debugger program
 */
export const LiveDebuggerProgramsRetrieveParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this live debugger program.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

/**
 * Retrieve probe-hit events emitted by this program from ClickHouse. Events are filtered by the program id stored in the `$program_id` property and returned most recent first.
 * @summary Get events emitted by a program
 */
export const LiveDebuggerProgramsEventsRetrieveParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this live debugger program.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const LiveDebuggerProgramsEventsRetrieveQueryParams = /* @__PURE__ */ zod.object({
    limit: zod.number().optional().describe('Maximum number of events to return (default 100, max 1000).'),
    offset: zod.number().optional().describe('Pagination offset.'),
})

/**
 * Soft-uninstall a program by transitioning its status to 'uninstalled'. The program record and any events it previously emitted remain queryable. Returns the updated program.
 * @summary Uninstall a live debugger program
 */
export const LiveDebuggerProgramsUninstallCreateParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this live debugger program.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})
