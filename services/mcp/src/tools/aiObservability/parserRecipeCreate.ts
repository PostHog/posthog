import { z } from 'zod'

import { mergeRecipes, RecipeNormalizer, type StoredRecipe, validateRecipeAgainstSample } from '@posthog/llm-normalizer'

import { getPostHogClient } from '@/lib/posthog'
import type { Context, ToolBase } from '@/tools/types'

// Mirrors MAX_SOURCE_LENGTH on the ParserRecipe model.
const MAX_SOURCE_LENGTH = 100_000

// The team's custom recipes are fetched with a fixed cap. A team with more custom
// recipes than this gets a slightly stale merge — acceptable, since the server still
// validates against the full event and the built-ins always run first.
const RECIPE_LIST_LIMIT = 300

const schema = z.object({
    name: z.string().min(1).max(255).describe('Short human-readable name for the recipe, shown in the parser editor.'),
    yaml_source: z
        .string()
        .min(1)
        .max(MAX_SOURCE_LENGTH)
        .describe(
            'The recipe as raw YAML. Call `llma-parser-recipe-reference` first for the DSL syntax and worked examples. The server compiles and validates this against the exact event before saving.'
        ),
    trace_id: z.string().min(1).describe('The `$ai_trace_id` of the trace containing the event to parse.'),
    event_uuid: z.string().min(1).describe('The UUID (`id`) of the specific event within the trace to parse.'),
})

type Params = z.infer<typeof schema>

interface ParserRecipeCreateResult {
    valid: boolean
    error?: string
    recipe_id?: string
    saved?: boolean
    already_recognized?: boolean
}

interface TraceEvent {
    id: string
    event: string
    properties?: Record<string, unknown>
}

interface Trace {
    events?: TraceEvent[]
}

interface EventSample {
    input: unknown
    output: unknown
    // Embeddings have no message-shaped output; treat that side as recognized so the
    // recipe only has to explain the input.
    outputRecognizedByDefault: boolean
}

// Extract the input/output sides by event type, mirroring `ConversationDisplay`.
function extractSample(eventName: string, properties: Record<string, unknown>): EventSample {
    if (eventName === '$ai_generation') {
        return {
            input: properties.$ai_input,
            output: properties.$ai_output_choices ?? properties.$ai_output,
            outputRecognizedByDefault: false,
        }
    }
    if (eventName === '$ai_embedding') {
        return { input: properties.$ai_input, output: undefined, outputRecognizedByDefault: true }
    }
    // Spans and everything else carry their payload in the `_state` fields.
    return {
        input: properties.$ai_input_state,
        output: properties.$ai_output_state,
        outputRecognizedByDefault: false,
    }
}

export const parserRecipeCreateHandler: ToolBase<typeof schema, ParserRecipeCreateResult>['handler'] = async (
    context: Context,
    params: Params
) => {
    const projectId = await context.stateManager.getProjectId()

    // The 1-year window mirrors the frontend trace fetch (`aiObservabilityTraceDataLogic`);
    // without it, older traces silently return no rows.
    const dateFrom = new Date(Date.now() - 365 * 24 * 3600 * 1000).toISOString()
    const traceResult = await context.api
        .query({ projectId: String(projectId) })
        .execute({ queryBody: { kind: 'TraceQuery', traceId: params.trace_id, dateRange: { date_from: dateFrom } } })
    if (!traceResult.success) {
        // Infra failures are exceptions; validation failures are results.
        throw new Error(`Failed to load trace ${params.trace_id}: ${traceResult.error.message}`)
    }

    const traces = (traceResult.data.results ?? []) as Trace[]
    const event = traces.flatMap((trace) => trace.events ?? []).find((candidate) => candidate.id === params.event_uuid)
    if (!event) {
        return { valid: false, error: 'event not found in trace — re-check trace_id and event_uuid' }
    }

    const properties = event.properties ?? {}
    const { input, output, outputRecognizedByDefault } = extractSample(event.event, properties)
    if (input === undefined && output === undefined) {
        // TraceQuery falls back to the shared events table where the heavy AI columns are
        // stripped, and `ai_events` has a retention TTL — a payload-less event can't prove
        // anything about a recipe, and normalizeMessages(undefined) would count as recognized.
        return {
            valid: false,
            error: 'the event payload is not available server-side (it likely aged out of retention) — the recipe cannot be validated against it',
        }
    }
    const tools = properties.$ai_tools

    const listResponse = await context.api.request<{ results?: Array<{ id: string; source: string }> }>({
        method: 'GET',
        path: `/api/projects/${projectId}/llm_analytics/parser_recipes/`,
        query: { limit: RECIPE_LIST_LIMIT },
    })
    const teamRecipes: StoredRecipe[] = (listResponse.results ?? []).map((row) => ({ id: row.id, source: row.source }))

    // Recompute recognition the way the browser does, so validation only demands the
    // sides that are currently unrecognized. The whole (possibly multi-MB) trace is
    // deserialized once here and discarded — the same order of work the browser does.
    const normalizer = new RecipeNormalizer(mergeRecipes(teamRecipes))
    const inputRecognized = normalizer.normalizeMessages(input, 'user', tools).recognized
    const outputRecognized = outputRecognizedByDefault || normalizer.normalizeMessages(output, 'assistant').recognized

    const verdict = validateRecipeAgainstSample(params.yaml_source, teamRecipes, {
        input,
        output,
        tools,
        inputRecognized,
        outputRecognized,
    })
    if (!verdict.valid) {
        return { valid: false, error: verdict.error }
    }

    // An event both sides of which are already recognized doesn't need a recipe; the
    // candidate then only has to compile. Flag it so the caller knows.
    const alreadyRecognized = inputRecognized && outputRecognized

    // A byte-identical recipe already exists — return it instead of saving a duplicate.
    const existing = teamRecipes.find((recipe) => recipe.source === params.yaml_source)
    if (existing) {
        return { valid: true, recipe_id: existing.id, ...(alreadyRecognized ? { already_recognized: true } : {}) }
    }

    // With both sides pre-recognized, validation was vacuous — the candidate proved
    // nothing, so persisting it team-wide would save an unproven recipe.
    if (alreadyRecognized) {
        return { valid: true, already_recognized: true }
    }

    try {
        const created = await context.api.request<{ id: string }>({
            method: 'POST',
            path: `/api/projects/${projectId}/llm_analytics/parser_recipes/`,
            body: { name: params.name, source: params.yaml_source },
        })
        return { valid: true, recipe_id: created.id }
    } catch (error) {
        // Capture before the soft return: the graceful result bypasses `handleToolError`,
        // the path that normally surfaces 5xx-class failures to observability.
        try {
            getPostHogClient().captureException(error, undefined, { tag: 'mcp', tool: 'llma-parser-recipe-create' })
        } catch {
            // Observability must never break the request.
        }
        // Only persistence failed — never make the agent rewrite a correct recipe.
        return { valid: true, saved: false, error: error instanceof Error ? error.message : String(error) }
    }
}

const tool = (): ToolBase<typeof schema, ParserRecipeCreateResult> => ({
    name: 'llma-parser-recipe-create',
    schema,
    handler: parserRecipeCreateHandler,
})

export default tool
