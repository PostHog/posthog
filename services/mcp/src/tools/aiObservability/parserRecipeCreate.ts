import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import { PostHogApiError, wrapError } from '@/lib/errors'
import { getPostHogClient } from '@/lib/posthog'
import { getToolRecoveryHint } from '@/lib/tool-error-hints'
import type { Context, ToolBase } from '@/tools/types'

// Mirrors MAX_SOURCE_LENGTH on the ParserRecipe model.
const MAX_SOURCE_LENGTH = 100_000

const schema = z.object({
    name: z.string().min(1).max(255).describe('Short human-readable name for the recipe, shown in the parser editor.'),
    yaml_source: z
        .string()
        .min(1)
        .max(MAX_SOURCE_LENGTH)
        .describe(
            'The recipe as raw YAML. Call `llma-parser-recipe-reference` first for the DSL syntax and worked examples. The server tests this against the exact event before saving.'
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

type ParserTest = Schemas.TraceNodeParserTest

function pathSegment(id: string): string {
    return Buffer.from(id, 'utf8').toString('base64url')
}

function apiErrorDetail(error: PostHogApiError): string {
    try {
        const body: unknown = JSON.parse(error.body)
        if (body && typeof body === 'object' && 'detail' in body && typeof body.detail === 'string') {
            return body.detail
        }
    } catch {
        // A body that is not JSON is the message itself.
    }
    return error.body
}

function failureReason(test: ParserTest): string {
    const sides = [
        ['input', test.input],
        ['output', test.output],
    ] as const
    const reasons = sides.flatMap(([name, side]) => {
        if (side.error?.source === 'existing_recipes') {
            return [
                `the team's existing parser recipes fail on the ${name}: ${side.error.message} — this is not a problem with your recipe`,
            ]
        }
        if (side.error) {
            return [`your recipe failed while parsing the ${name}: ${side.error.message}`]
        }
        if (side.broken) {
            return [
                `the ${name} is parsed without your recipe but not with it — narrow your rules so they leave that side alone`,
            ]
        }
        if (side.neededFixing && !side.fixed) {
            return [`the parser does not make the ${name} parsed — write rules that match the shapes in the sample`]
        }
        return []
    })
    return reasons.join('; ')
}

async function testParser(
    context: Context,
    projectId: string,
    params: Params
): Promise<ParserTest | ParserRecipeCreateResult> {
    try {
        return await context.api.request<ParserTest>({
            method: 'POST',
            path: `/api/projects/${projectId}/ai_observability/traces/${pathSegment(params.trace_id)}/nodes/${pathSegment(params.event_uuid)}/parser_test/`,
            body: { source: params.yaml_source },
        })
    } catch (error) {
        if (error instanceof PostHogApiError && error.status === 400) {
            return { valid: false, error: `the recipe does not compile: ${apiErrorDetail(error)}` }
        }
        if (error instanceof PostHogApiError && error.status === 404) {
            return {
                valid: false,
                error: 'the event was not found in this trace, or it is past AI events retention — re-check trace_id and event_uuid, and if they are right, the event can no longer be read',
            }
        }
        // Infra failures are exceptions; validation failures are results.
        throw wrapError(`Failed to test the recipe against event ${params.event_uuid}`, error)
    }
}

export const parserRecipeCreateHandler: ToolBase<typeof schema, ParserRecipeCreateResult>['handler'] = async (
    context: Context,
    params: Params
) => {
    const projectId = String(await context.stateManager.getProjectId())

    const test = await testParser(context, projectId, params)
    if ('valid' in test) {
        return test
    }
    if (!test.input.neededFixing && !test.output.neededFixing) {
        return { valid: true, already_recognized: true }
    }
    if (!test.passed) {
        return { valid: false, error: failureReason(test) }
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
            const apiKey = await context.stateManager.getApiKey()
            getPostHogClient().captureException(error, undefined, {
                tag: 'mcp',
                tool: 'llma-parser-recipe-create',
                suppress_analytics: apiKey.suppress_analytics === true,
            })
        } catch {
            // Observability must never break the request.
        }
        // Only persistence failed — never make the agent rewrite a correct recipe.
        const message = error instanceof Error ? error.message : String(error)
        const recoveryHint = error instanceof PostHogApiError ? getToolRecoveryHint(error) : undefined
        return { valid: true, saved: false, error: [message, recoveryHint].filter(Boolean).join(' ') }
    }
}

const tool = (): ToolBase<typeof schema, ParserRecipeCreateResult> => ({
    name: 'llma-parser-recipe-create',
    schema,
    handler: parserRecipeCreateHandler,
})

export default tool
