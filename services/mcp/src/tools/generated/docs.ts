// AUTO-GENERATED from products/docs/mcp/tools.yaml + OpenAPI — do not edit
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import {
    DocsDataPointsSubmitCreateBody,
    DocsSearchBody,
    DocsWatchesBriefCreateBody,
    DocsWatchesVerdictCreateBody,
} from '@/generated/docs/api'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

const DocsSearchSchema = DocsSearchBody

const docsSearch = (): ToolBase<typeof DocsSearchSchema, Schemas.DocsSearchResponse> => ({
    name: 'docs-search',
    schema: DocsSearchSchema,
    handler: async (context: Context, params: z.infer<typeof DocsSearchSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.query !== undefined) {
            body['query'] = params.query
        }
        const result = await context.api.request<Schemas.DocsSearchResponse>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/mcp_tools/docs_search/`,
            body,
        })
        return result
    },
})

const DocDataPointSubmitSchema = DocsDataPointsSubmitCreateBody.extend({
    request_id: DocsDataPointsSubmitCreateBody.shape['request_id'].describe(
        'The request id given in the task description. Copy it exactly.'
    ),
    query: DocsDataPointsSubmitCreateBody.shape['query'].describe(
        'One HogQL SELECT (or WITH … SELECT). One cell for a number, date and number columns for a trend, anything else for a table. No semicolon, no other statements.'
    ),
    label: DocsDataPointsSubmitCreateBody.shape['label'].describe(
        'What it shows, in a few words, as the reader will see it. For example "teams with replay on this month".'
    ),
    note: DocsDataPointsSubmitCreateBody.shape['note'].describe(
        'One short line for the reader when the number needs a caveat, or why there is no answer when status is none. Leave empty otherwise.'
    ),
})

const docDataPointSubmit = (): ToolBase<typeof DocDataPointSubmitSchema, Schemas.DataPointSubmitResult> => ({
    name: 'doc-data-point-submit',
    schema: DocDataPointSubmitSchema,
    handler: async (context: Context, params: z.infer<typeof DocDataPointSubmitSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.request_id !== undefined) {
            body['request_id'] = params.request_id
        }
        if (params.status !== undefined) {
            body['status'] = params.status
        }
        if (params.query !== undefined) {
            body['query'] = params.query
        }
        if (params.label !== undefined) {
            body['label'] = params.label
        }
        if (params.note !== undefined) {
            body['note'] = params.note
        }
        const result = await context.api.request<Schemas.DataPointSubmitResult>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/docs/data_points/submit/`,
            body,
        })
        return result
    },
})

const DocWatchBriefSubmitSchema = DocsWatchesBriefCreateBody.extend({
    request_id: DocsWatchesBriefCreateBody.shape['request_id'].describe(
        'The request id given in the task description. Copy it exactly.'
    ),
    claim: DocsWatchesBriefCreateBody.shape['claim'].describe('The hypothesis in one sentence, as the page states it.'),
    confirms: DocsWatchesBriefCreateBody.shape['confirms'].describe(
        'What in the data would confirm the claim, in one line.'
    ),
    refutes: DocsWatchesBriefCreateBody.shape['refutes'].describe(
        'What in the data would refute the claim, in one line.'
    ),
    evidence: DocsWatchesBriefCreateBody.shape['evidence'].describe(
        'Up to four {label, query} pairs. Each query is one HogQL SELECT returning one number, or a date and a number per row. No semicolon.'
    ),
    signals: DocsWatchesBriefCreateBody.shape['signals'].describe(
        'Up to six short lines naming what to follow, for example "signup_completed events by country" or "errors in the checkout flow".'
    ),
})

const docWatchBriefSubmit = (): ToolBase<typeof DocWatchBriefSubmitSchema, Schemas.WatchBriefSubmitResult> => ({
    name: 'doc-watch-brief-submit',
    schema: DocWatchBriefSubmitSchema,
    handler: async (context: Context, params: z.infer<typeof DocWatchBriefSubmitSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.request_id !== undefined) {
            body['request_id'] = params.request_id
        }
        if (params.claim !== undefined) {
            body['claim'] = params.claim
        }
        if (params.confirms !== undefined) {
            body['confirms'] = params.confirms
        }
        if (params.refutes !== undefined) {
            body['refutes'] = params.refutes
        }
        if (params.evidence !== undefined) {
            body['evidence'] = params.evidence
        }
        if (params.signals !== undefined) {
            body['signals'] = params.signals
        }
        const result = await context.api.request<Schemas.WatchBriefSubmitResult>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/docs/watches/brief/`,
            body,
        })
        return result
    },
})

const DocWatchVerdictSubmitSchema = DocsWatchesVerdictCreateBody.extend({
    request_id: DocsWatchesVerdictCreateBody.shape['request_id'].describe(
        'The request id given in the task description. Copy it exactly.'
    ),
    verdict: DocsWatchesVerdictCreateBody.shape['verdict'].describe(
        'holding when the evidence still supports the claim, moved when it shifted but is not decided, confirmed or refuted when the data leaves no doubt.'
    ),
    reason: DocsWatchesVerdictCreateBody.shape['reason'].describe(
        'One line the reader sees, with the number that decides it.'
    ),
})

const docWatchVerdictSubmit = (): ToolBase<typeof DocWatchVerdictSubmitSchema, unknown> => ({
    name: 'doc-watch-verdict-submit',
    schema: DocWatchVerdictSubmitSchema,
    handler: async (context: Context, params: z.infer<typeof DocWatchVerdictSubmitSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.request_id !== undefined) {
            body['request_id'] = params.request_id
        }
        if (params.verdict !== undefined) {
            body['verdict'] = params.verdict
        }
        if (params.reason !== undefined) {
            body['reason'] = params.reason
        }
        const result = await context.api.request<unknown>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/docs/watches/verdict/`,
            body,
        })
        return result
    },
})

export const GENERATED_TOOLS: Record<string, () => ToolBase<ZodObjectAny>> = {
    'docs-search': docsSearch,
    'doc-data-point-submit': docDataPointSubmit,
    'doc-watch-brief-submit': docWatchBriefSubmit,
    'doc-watch-verdict-submit': docWatchVerdictSubmit,
}
