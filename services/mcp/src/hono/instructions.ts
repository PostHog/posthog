import { RESOURCE_URI_META_KEY } from '@modelcontextprotocol/ext-apps/server'
import type { Tool as McpTool } from '@modelcontextprotocol/sdk/types.js'

import type { QueryToolInfo } from '@/lib/instructions'
import {
    type InstructionsContext,
    InstructionsFormatter,
    schemaDiscoveryViaSqlEnabled,
} from '@/lib/instructions-formatter'
import type { EvaluatedFlags } from '@/lib/posthog/flags'
import { formatPrompt } from '@/lib/utils'
import { RENDER_UI_RESOURCE_URI } from '@/resources/ui-apps.generated'
import EXECUTE_SQL_PROMPT from '@/templates/execute-sql-prompt.md'
import SCHEMA_DISCOVERY_INFOSCHEMA from '@/templates/sections/schema-discovery-infoschema.md'
import SCHEMA_DISCOVERY_LEGACY from '@/templates/sections/schema-discovery-legacy.md'
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
            featureFlags: state.toolFeatureFlags,
            renderUiEnabled: state.renderUiEnabled,
            metadata: state.metadata,
            groupTypes: state.groupTypes,
        }
    }

    buildExecToolEntry(state: ResolvedState): McpTool {
        const commandReference = this.buildExecCommandReference(state)
        const ExecSchema = { command: { type: 'string', description: commandReference } }

        return {
            name: 'exec',
            title: 'Execute PostHog command',
            description: this.formatter.buildExecToolDescription(),
            inputSchema: { type: 'object', properties: ExecSchema, required: ['command'] },
        }
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
        return this.formatter.buildExecCommandReference(ctx, {
            stripEnvContext: supportsInstructions,
            keepEnvContext,
        })
    }

    buildExecToolDescription(): string {
        return this.formatter.buildExecToolDescription()
    }

    getGuidelines(): string {
        return this.guidelines
    }

    formatExecuteSqlDescription(featureFlags?: EvaluatedFlags): string {
        const schemaDiscovery = schemaDiscoveryViaSqlEnabled(featureFlags)
            ? SCHEMA_DISCOVERY_INFOSCHEMA
            : SCHEMA_DISCOVERY_LEGACY
        return formatPrompt(EXECUTE_SQL_PROMPT, {
            guidelines: this.guidelines.trim(),
            schema_discovery: schemaDiscovery.trim(),
        })
    }
}
