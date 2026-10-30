import { RESOURCE_URI_META_KEY } from '@modelcontextprotocol/ext-apps/server'
import type { Tool as McpTool } from '@modelcontextprotocol/sdk/types.js'
import { z } from 'zod'

import { markExecPayload, type ToolResultPayload } from '@/lib/build-tool-result'
import { DISPATCHABLE_APP_KEYS, RENDER_UI_RESOURCE_URI, URI_MAP, type UiAppKey } from '@/resources/ui-apps.generated'
import RENDER_UI_EXPLAIN_CHART from '@/templates/render-ui-explain-chart.md'
import RENDER_UI_PROMPT from '@/templates/render-ui-prompt.md'

import { type Context, type Tool, type ZodObjectAny } from './types'

export const RENDER_UI_TOOL_NAME = 'render-ui'
export const RENDER_UI_TOOL_TITLE = 'Render a PostHog visualization'
export const RENDER_UI_TOOL_DESCRIPTION = RENDER_UI_PROMPT.trim()

export function renderUiDescription(renderableNames: string[]): string {
    return renderableNames.includes('explain-chart')
        ? `${RENDER_UI_TOOL_DESCRIPTION}\n\n${RENDER_UI_EXPLAIN_CHART.trim()}`
        : RENDER_UI_TOOL_DESCRIPTION
}

// Reverse of URI_MAP so a tool's `_meta.ui.resourceUri` resolves back to its app key.
const URI_TO_APP_KEY = new Map<string, UiAppKey>(
    Object.entries(URI_MAP).map(([appKey, uri]) => [uri, appKey as UiAppKey])
)

const DISPATCHABLE = new Set<UiAppKey>(DISPATCHABLE_APP_KEYS)

/** The dispatchable app key for a tool, or undefined when it has no renderable UI app. */
function toDispatchableAppKey(tool: Pick<McpTool, '_meta'>): UiAppKey | undefined {
    const ui = tool._meta?.ui
    if (!ui || typeof ui !== 'object' || !('resourceUri' in ui) || typeof ui.resourceUri !== 'string') {
        return undefined
    }
    const appKey = URI_TO_APP_KEY.get(ui.resourceUri)
    return appKey && DISPATCHABLE.has(appKey) ? appKey : undefined
}

/**
 * Names of the tools `render-ui` can render — those whose UI app exposes a reusable view.
 * Restricted to read-only tools: `render-ui` is annotated read-only, so it must not be a
 * back door for dispatching state-changing tools (e.g. `survey-launch`, `workflows-create`).
 */
export function getRenderableToolNames(allTools: Pick<McpTool, 'name' | 'annotations' | '_meta'>[]): string[] {
    return allTools
        .filter((tool) => tool.annotations?.readOnlyHint && toDispatchableAppKey(tool) !== undefined)
        .map((tool) => tool.name)
}

/** OpenAI caches the advertised catalog across accounts, so execution must
 *  validate the same input shape against the current account's allowed tools. */
export function makeRenderUiSchema(
    toolNames: [string, ...string[]]
): z.ZodObject<{ tool_name: z.ZodEnum<Record<string, string>>; tool_input: z.ZodOptional<z.ZodRecord> }> {
    return z.object({
        tool_name: z
            .enum(toolNames)
            .describe('A tool that has a UI app — its visualization will be rendered for the user.'),
        tool_input: z
            .record(z.string(), z.unknown())
            .optional()
            .describe('The generated input for that tool. The UI app uses it to fetch and render the visualization.'),
    })
}

type RenderUiSchema = ReturnType<typeof makeRenderUiSchema>

/**
 * Builds the `render-ui` umbrella tool. Returns `null` when no tool in `allTools`
 * has a renderable UI app (a `z.enum` needs at least one value, and there is
 * nothing to render anyway). Unlike the per-entity tools, this one does not run
 * the inner tool: it emits a render directive (`{ tool_name, tool_input, app_key }`
 * + the render-ui resourceUri) and the UI app fetches its own data.
 */
export function createRenderUiTool(
    allTools: Tool<ZodObjectAny>[],
    context: Context,
    mcpClientName?: string
): Tool<RenderUiSchema> | null {
    const renderableNames = getRenderableToolNames(allTools)
    if (renderableNames.length === 0) {
        return null
    }
    const schema = makeRenderUiSchema(renderableNames as [string, ...string[]])

    return {
        name: RENDER_UI_TOOL_NAME,
        title: RENDER_UI_TOOL_TITLE,
        description: renderUiDescription(renderableNames),
        schema,
        scopes: [],
        annotations: {
            destructiveHint: false,
            idempotentHint: true,
            openWorldHint: false,
            readOnlyHint: true,
        },
        // Advertise the umbrella UI resource on the tool definition itself.
        // MCP Apps hosts (e.g. Claude) discover renderable tools from `tools/list`
        // `_meta.ui.resourceUri`, pre-fetch the template, and only mount the iframe
        // for a tool declared this way — the result-level `_meta` alone is ignored.
        // `registerTool` back-fills the legacy `ui/resourceUri` key from this.
        _meta: {
            ui: { resourceUri: RENDER_UI_RESOURCE_URI },
            [RESOURCE_URI_META_KEY]: RENDER_UI_RESOURCE_URI,
        },
        handler: async (_context: Context, params: z.infer<RenderUiSchema>) => {
            const tool = allTools.find((t) => t.name === params.tool_name)
            const appKey = tool ? toDispatchableAppKey(tool) : undefined
            if (!tool || !appKey) {
                throw new Error(`Tool "${params.tool_name}" does not have a renderable UI app.`)
            }

            const toolInput = params.tool_input ?? {}
            // `render-ui` only emits a render directive — it never executes the inner tool,
            // so the inner tool is deliberately not counted in per-tool call metrics. The
            // umbrella call itself is tracked under `render-ui` by the executor.
            const distinctId = await context.getDistinctId()

            const payload: ToolResultPayload = {
                content: [
                    {
                        type: 'text',
                        text: [`Rendering the ${tool.name} visualization for the user.`, tool.renderedNote]
                            .filter(Boolean)
                            .join(' '),
                    },
                ],
                structuredContent: {
                    tool_name: tool.name,
                    tool_input: toolInput,
                    app_key: appKey,
                    _analytics: {
                        distinctId,
                        toolName: RENDER_UI_TOOL_NAME,
                        ...(mcpClientName ? { mcpClientName } : {}),
                    },
                },
                _meta: {
                    ui: { resourceUri: RENDER_UI_RESOURCE_URI },
                    [RESOURCE_URI_META_KEY]: RENDER_UI_RESOURCE_URI,
                },
            }
            return markExecPayload(payload)
        },
    }
}
