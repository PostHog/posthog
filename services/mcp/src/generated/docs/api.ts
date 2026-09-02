/**
 * Auto-generated from the Django backend OpenAPI schema.
 * MCP service uses these Zod schemas for generated tool handlers.
 * To regenerate: hogli build:openapi
 *
 * PostHog API - MCP 1 enabled ops
 * OpenAPI spec version: 1.0.0
 */
import * as zod from 'zod'

/**
 * Run a hybrid (semantic + full-text) RAG search over the PostHog documentation via Inkeep. Returns a markdown body with title, URL, and excerpt for each match for the agent to cite back to the user.
 * @summary Search PostHog documentation
 */
export const DocsSearchParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const DocsSearchBody = /* @__PURE__ */ zod.object({
    query: zod
        .string()
        .describe(
            'Natural-language description of what to find in the PostHog documentation. Inkeep performs hybrid (semantic + full-text) RAG, so phrase the query the way a user would ask the question.'
        ),
})

/**
 * Called by the agent that a page asked for a data point. The query is checked and run once; on ok the page shows it live from then on. Submit again with the same request id to replace it.
 * @summary Submit the query behind a data point
 */
export const DocsDataPointsSubmitCreateParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const docsDataPointsSubmitCreateBodyRequestIdMax = 64

export const docsDataPointsSubmitCreateBodyStatusDefault = `ok`
export const docsDataPointsSubmitCreateBodyQueryDefault = ``
export const docsDataPointsSubmitCreateBodyLabelDefault = ``
export const docsDataPointsSubmitCreateBodyLabelMax = 120

export const docsDataPointsSubmitCreateBodyNoteDefault = ``
export const docsDataPointsSubmitCreateBodyNoteMax = 400

export const DocsDataPointsSubmitCreateBody = /* @__PURE__ */ zod
    .object({
        request_id: zod
            .string()
            .max(docsDataPointsSubmitCreateBodyRequestIdMax)
            .describe('The request id named in the task.'),
        status: zod
            .enum(['ok', 'none'])
            .describe('\* `ok` - ok\n\* `none` - none')
            .default(docsDataPointsSubmitCreateBodyStatusDefault)
            .describe(
                "ok: the query answers the question. none: this project's data cannot answer it.\n\n\* `ok` - ok\n\* `none` - none"
            ),
        query: zod
            .string()
            .default(docsDataPointsSubmitCreateBodyQueryDefault)
            .describe('A HogQL SELECT that returns exactly one row and one column. Required unless status is none.'),
        label: zod
            .string()
            .max(docsDataPointsSubmitCreateBodyLabelMax)
            .default(docsDataPointsSubmitCreateBodyLabelDefault)
            .describe('What the data point measures, in a few words. The reader sees this on it.'),
        note: zod
            .string()
            .max(docsDataPointsSubmitCreateBodyNoteMax)
            .default(docsDataPointsSubmitCreateBodyNoteDefault)
            .describe('One short line for the reader: a caveat, or with status none, why there is no answer.'),
    })
    .describe('An agent handing in the query behind a data point a page asked for.')
