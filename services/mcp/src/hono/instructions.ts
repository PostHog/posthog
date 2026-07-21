import { RESOURCE_URI_META_KEY } from '@modelcontextprotocol/ext-apps/server'
import type { Tool as McpTool } from '@modelcontextprotocol/sdk/types.js'

import { PRODUCT_DATA_CATALOG_FLAG } from '@/lib/constants'
import type { QueryToolInfo } from '@/lib/instructions'
import { type InstructionsContext, InstructionsFormatter } from '@/lib/instructions-formatter'
import type { EvaluatedFlags } from '@/lib/posthog/flags'
import { formatPrompt } from '@/lib/utils'
import { RENDER_UI_RESOURCE_URI } from '@/resources/ui-apps.generated'
import EXECUTE_SQL_PROMPT from '@/templates/execute-sql-prompt.md'
import CATALOG_TRUST_DISCOVERY from '@/templates/sections/catalog-trust-discovery.md'
import METRIC_DISCOVERY from '@/templates/sections/metric-discovery.md'
import SCHEMA_DISCOVERY from '@/templates/sections/schema-discovery.md'
import { EXEC_READ_TOOL_NAME, EXEC_WRITE_TOOL_NAME } from '@/tools/exec'
import { ExecHelpCatalog } from '@/tools/exec-help'
import {
    getRenderableToolNames,
    makeRenderUiSchema,
    RENDER_UI_TOOL_DESCRIPTION,
    RENDER_UI_TOOL_NAME,
    RENDER_UI_TOOL_TITLE,
} from '@/tools/render-ui'
import { getToolDefinition } from '@/tools/toolDefinitions'

import type { ResolvedState } from './request-state-resolver'
import { toMcpInputSchema } from './tool-catalog'

export class InstructionsBuilder {
    private readonly formatter: InstructionsFormatter
    private readonly guidelines: string

    constructor(guidelines: string, formatter?: InstructionsFormatter) {
        this.guidelines = guidelines
        this.formatter = formatter ?? new InstructionsFormatter()
    }

    build(state: ResolvedState): string {
        const supportsInstructions = state.clientProfile.capabilities.supportsInstructions
        if (!supportsInstructions) {
            return ''
        }

        const ctx = this.buildContext(state)
        if (state.useSingleExec) {
            return this.formatter.buildExecInstructions(ctx)
        }
        return this.formatter.buildToolsInstructions(ctx)
    }

    buildContext(state: ResolvedState): InstructionsContext {
        return {
            guidelines: this.guidelines,
            tools: state.allTools.map((t) => ({
                name: t.name,
                category: getToolDefinition(t.name).category,
            })),
            queryTools: state.allTools
                .filter((t) => t.name.startsWith('query-'))
                .map((t) => {
                    const def = getToolDefinition(t.name)
                    return {
                        name: t.name,
                        title: def.title,
                        ...(def.system_prompt_hint ? { systemPromptHint: def.system_prompt_hint } : {}),
                    } as QueryToolInfo
                }),
            renderUiEnabled: state.renderUiEnabled,
            metadata: state.metadata,
            groupTypes: state.groupTypes,
            dataCatalogEnabled: state.toolFeatureFlags?.[PRODUCT_DATA_CATALOG_FLAG] === true,
        }
    }

    private buildExecEntry(
        state: ResolvedState,
        opts: { name: string; title: string; description: string; readOnly: boolean }
    ): McpTool {
        const commandReference = this.buildExecCommandReference(state)
        const ExecSchema = { command: { type: 'string', description: commandReference } }

        return {
            name: opts.name,
            title: opts.title,
            description: opts.description,
            inputSchema: { type: 'object', properties: ExecSchema, required: ['command'] },
            // A read/write split at the advertised-tool level is what lets a client
            // gate on `readOnlyHint`: the read-only dispatcher is safe to always-allow,
            // while the write dispatcher keeps prompting for confirmation.
            annotations: {
                destructiveHint: false,
                idempotentHint: false,
                openWorldHint: true,
                readOnlyHint: opts.readOnly,
            },
        }
    }

    buildExecToolEntry(state: ResolvedState): McpTool {
        return this.buildExecEntry(state, {
            name: EXEC_READ_TOOL_NAME,
            title: 'Query PostHog (read-only)',
            description: this.formatter.buildExecReadToolDescription(),
            readOnly: true,
        })
    }

    buildExecWriteToolEntry(state: ResolvedState): McpTool {
        return this.buildExecEntry(state, {
            name: EXEC_WRITE_TOOL_NAME,
            title: 'Create, update & delete in PostHog',
            description: this.formatter.buildExecWriteToolDescription(),
            readOnly: false,
        })
    }

    buildRenderUiToolEntry(state: ResolvedState): McpTool | null {
        const toolNames = getRenderableToolNames(state.allTools)
        if (toolNames.length === 0) {
            return null
        }
        return {
            name: RENDER_UI_TOOL_NAME,
            title: RENDER_UI_TOOL_TITLE,
            description: RENDER_UI_TOOL_DESCRIPTION,
            // Derived from the same zod schema the executor validates with, so the
            // advertised contract (enum, descriptions, required) cannot drift from it.
            inputSchema: toMcpInputSchema(makeRenderUiSchema(toolNames as [string, ...string[]])),
            // Advertise the umbrella UI resource so MCP Apps hosts (e.g. Claude) discover
            // render-ui as renderable from `tools/list` and mount its iframe. Both the
            // modern and legacy keys are emitted since this entry isn't normalized downstream.
            _meta: {
                ui: { resourceUri: RENDER_UI_RESOURCE_URI },
                [RESOURCE_URI_META_KEY]: RENDER_UI_RESOURCE_URI,
            },
        }
    }

    buildExecCommandReference(state: ResolvedState): string {
        const supportsInstructions = state.clientProfile.capabilities.supportsInstructions
        // Claude web/desktop report `supportsInstructions` but never surface the
        // `instructions` payload to the model, so its env-context (tool domains,
        // project metadata, group types) would be lost. Keep it on the exec command
        // description for those chat hosts only — Cowork surfaces instructions
        // normally and gets env-context through them. (Codex, which reports
        // `supportsInstructions: false`, already gets the full env-context via the
        // un-stripped path.)
        const keepEnvContext = state.clientProfile.isClaudeChatHost()
        const ctx = this.buildContext(state)
        if (keepEnvContext) {
            return this.formatter.buildClaudeExecCommandReference(ctx)
        }
        return this.formatter.buildExecCommandReference(ctx, {
            stripEnvContext: supportsInstructions,
        })
    }

    buildExecHelpCatalog(state: ResolvedState): ExecHelpCatalog | undefined {
        if (!state.clientProfile.isClaudeChatHost()) {
            return undefined
        }
        return new ExecHelpCatalog(this.formatter.buildClaudeExecHelpEntries(this.buildContext(state)))
    }

    buildExecToolDescription(): string {
        return this.formatter.buildExecToolDescription()
    }

    getGuidelines(): string {
        return this.guidelines
    }

    formatExecuteSqlDescription(toolFeatureFlags?: EvaluatedFlags): string {
        // Data-catalog discovery is spliced into the same section so a flag-off render stays
        // byte-identical to the un-gated prompt (no stray placeholder gaps).
        const dataCatalogEnabled = toolFeatureFlags?.[PRODUCT_DATA_CATALOG_FLAG] === true
        const schemaDiscovery = dataCatalogEnabled
            ? `${SCHEMA_DISCOVERY.trim()}\n\n${CATALOG_TRUST_DISCOVERY.trim()}\n\n${METRIC_DISCOVERY.trim()}`
            : SCHEMA_DISCOVERY.trim()
        return formatPrompt(EXECUTE_SQL_PROMPT, {
            guidelines: this.guidelines.trim(),
            schema_discovery: schemaDiscovery,
        })
    }
}
