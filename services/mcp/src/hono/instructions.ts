import { RESOURCE_URI_META_KEY } from '@modelcontextprotocol/ext-apps/server'
import type { Tool as McpTool } from '@modelcontextprotocol/sdk/types.js'

import type { QueryToolInfo } from '@/lib/instructions'
import { type CodeExecutionLevel, type InstructionsContext, InstructionsFormatter } from '@/lib/instructions-formatter'
import { formatPrompt } from '@/lib/utils'
import { RENDER_UI_RESOURCE_URI } from '@/resources/ui-apps.generated'
import EXECUTE_SQL_PROMPT from '@/templates/execute-sql-prompt.md'
import SCHEMA_DISCOVERY from '@/templates/sections/schema-discovery.md'
import { sandboxExecutionAvailable } from '@/tools/code-exec/availability'
import { CODE_EXECUTION_FEATURE_FLAG, CODE_FIRST_FEATURE_FLAG } from '@/tools/code-exec/constants'
import { SCRIPT_PARAM_DESCRIPTION } from '@/tools/exec'
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
            codeExecution: this.resolveCodeExecutionLevel(state),
            // The formatter additionally requires `codeExecution: 'full'` before
            // rendering the code-first arm — flag semantics live there.
            codeFirstEnabled: state.toolFeatureFlags?.[CODE_FIRST_FEATURE_FLAG] === true,
        }
    }

    /**
     * Advertised code-execution command set for this process (spec §4.2/§4.4):
     * the flag turns the surface on everywhere, and the level selects between
     * the full-sandbox and fast-path-only `run` documentation — the same probe
     * the executor wiring uses, so the instructions can never promise script
     * capability the dispatcher rejects.
     */
    private resolveCodeExecutionLevel(state: ResolvedState): CodeExecutionLevel {
        if (state.toolFeatureFlags?.[CODE_EXECUTION_FEATURE_FLAG] !== true) {
            return 'off'
        }
        return sandboxExecutionAvailable() ? 'full' : 'fast-path'
    }

    buildExecToolEntry(state: ResolvedState): McpTool {
        const commandReference = this.buildExecCommandReference(state)
        // Hand-built rather than derived from `makeExecSchema` — keep the shape and
        // the shared `SCRIPT_PARAM_DESCRIPTION` in sync with `src/tools/exec.ts`.
        // `script` is only advertised where `run` exists: on a flag-off server its
        // description would steer agents into an unknown command, and every spare
        // char inside `inputSchema.properties` counts against claude.ai's silent
        // per-tool registry cap.
        const ExecSchema = {
            command: { type: 'string', description: commandReference },
            ...(this.resolveCodeExecutionLevel(state) !== 'off'
                ? { script: { type: 'string', description: SCRIPT_PARAM_DESCRIPTION } }
                : {}),
        }

        return {
            name: 'exec',
            title: 'Execute PostHog command',
            description: this.buildExecToolDescription(state),
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

    buildExecToolDescription(state: ResolvedState): string {
        return this.formatter.buildExecToolDescription(this.buildContext(state))
    }

    getGuidelines(): string {
        return this.guidelines
    }

    formatExecuteSqlDescription(): string {
        return formatPrompt(EXECUTE_SQL_PROMPT, {
            guidelines: this.guidelines.trim(),
            schema_discovery: SCHEMA_DISCOVERY.trim(),
        })
    }
}
