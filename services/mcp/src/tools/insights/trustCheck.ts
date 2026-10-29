import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import { normalizeParamAliases } from '@/tools/cast-helpers'
import { withAgentNote, type WithAgentNote } from '@/tools/tool-utils'
import type { Context, ToolBase } from '@/tools/types'

const schema = z.preprocess(
    normalizeParamAliases({ id: ['insightId', 'insight_id', 'short_id', 'shortId'] }),
    z
        .object({
            id: z
                .union([z.number(), z.string()])
                .optional()
                .describe('Numeric id or 8-character `short_id` of a saved insight. Pass this or `query`, not both.'),
            query: z
                .object({ kind: z.string() })
                .catchall(z.unknown())
                .optional()
                .describe(
                    'An insight query that is not saved yet, in the shape `insight-create` takes, for example ' +
                        '`{ "kind": "InsightVizNode", "source": { "kind": "TrendsQuery", "series": [{ "kind": "EventsNode", ' +
                        '"event": "$pageview" }], "dateRange": { "date_from": "-30d" } } }`. Pass this or `id`, not both.'
                ),
        })
        .refine((params) => (params.id === undefined) !== (params.query === undefined), {
            message: 'Pass either `id` for a saved insight or `query` for a query that is not saved yet, not both.',
        })
)

type Params = z.infer<typeof schema>

type Result = WithAgentNote<Schemas.InsightDataChecks>

const AGENT_NOTE =
    'When a check has the level `warning` or `problem`, tell the user what it found in one sentence, with its share ' +
    "of the events, and offer the fix. Do not change the insight, the query or the project's filter settings before " +
    'the user agrees. When every check passed, say so in a few words. Do not list the checks that passed. When the ' +
    '`status` is `partial`, say which checks did not run and give each `skip_reason` in plain words.'

// An agent's call is already a request to check, so it runs the full check, whatever it reads.
const FULL_DEPTH = { depth: 'full' }

const insightTrustCheck = (): ToolBase<typeof schema, Result> => ({
    name: 'insight-trust-check',
    schema,
    handler: async (context: Context, params: Params) => {
        const { id, query } = params
        const projectId = encodeURIComponent(await context.stateManager.getProjectId())
        const result =
            id !== undefined
                ? await context.api.request<Schemas.InsightDataChecks>({
                      method: 'GET',
                      path: `/api/projects/${projectId}/insights/${encodeURIComponent(String(id))}/data_checks/`,
                      query: FULL_DEPTH,
                  })
                : await context.api.request<Schemas.InsightDataChecks>({
                      method: 'POST',
                      path: `/api/projects/${projectId}/insights/data_checks/`,
                      body: { query, ...FULL_DEPTH },
                  })
        return withAgentNote(result, AGENT_NOTE)
    },
})

export default insightTrustCheck
