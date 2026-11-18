/**
 * Auto-generated from the Django backend OpenAPI schema.
 * MCP service uses these Zod schemas for generated tool handlers.
 * To regenerate: hogli build:openapi
 *
 * PostHog API - MCP 3 enabled ops
 * OpenAPI spec version: 1.0.0
 */
import * as zod from 'zod'

/**
 * List the emails one workflow or broadcast sent, newest first. Sends are read from the `$workflows_email_*` events, which are only recorded while the project's engagement events setting is on.
 * @summary List a workflow's email sends
 */
export const WorkflowEmailLogListParams = () => zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const workflowEmailLogListQueryLimitDefault = 50
export const workflowEmailLogListQueryLimitMax = 200

export const workflowEmailLogListQueryOffsetDefault = 0
export const workflowEmailLogListQueryOffsetMin = 0

export const WorkflowEmailLogListQueryParams = () => zod.object({
    date_from: zod.iso
        .datetime({ offset: true })
        .optional()
        .describe('Only sends at or after this time. Defaults to 7 days ago.'),
    date_to: zod.iso.datetime({ offset: true }).optional().describe('Only sends before this time. Defaults to now.'),
    limit: zod
        .number()
        .min(1)
        .max(workflowEmailLogListQueryLimitMax)
        .default(workflowEmailLogListQueryLimitDefault)
        .describe('Page size.'),
    offset: zod
        .number()
        .min(workflowEmailLogListQueryOffsetMin)
        .default(workflowEmailLogListQueryOffsetDefault)
        .describe('Sends to skip.'),
    workflow_id: zod.string().describe('The workflow or broadcast whose sends to list.'),
})

/**
 * Get one email a workflow sent, with its delivery timeline. Sends are read from the `$workflows_email_*` events, which are only recorded while the project's engagement events setting is on.
 * @summary Get a workflow email send
 */
export const WorkflowEmailLogRetrieveParams = () => zod.object({
    id: zod.string().describe('The workflow run that sent the email, the `invocation_id` of a send.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const workflowEmailLogRetrieveQueryActionIdMax = 200

export const WorkflowEmailLogRetrieveQueryParams = () => zod.object({
    action_id: zod
        .string()
        .min(1)
        .max(workflowEmailLogRetrieveQueryActionIdMax)
        .describe('The email step that sent the email, the `action_id` of a send.'),
})

/**
 * The recipient's events in the 7 days before and after one workflow email, with the sessions they belong to.
 * @summary Get what a workflow email's recipient did around the send
 */
export const WorkflowEmailLogActivityRetrieveParams = () => zod.object({
    id: zod.string().describe('The workflow run that sent the email, the `invocation_id` of a send.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const workflowEmailLogActivityRetrieveQueryActionIdMax = 200

export const WorkflowEmailLogActivityRetrieveQueryParams = () => zod.object({
    action_id: zod
        .string()
        .min(1)
        .max(workflowEmailLogActivityRetrieveQueryActionIdMax)
        .describe('The email step that sent the email, the `action_id` of a send.'),
})
