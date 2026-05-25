import type { Tool as McpTool } from '@modelcontextprotocol/sdk/types.js'

import { hasScope } from '@/lib/api'
import type { QueryToolInfo } from '@/lib/instructions'
import { type InstructionsContext, InstructionsFormatter } from '@/lib/instructions-formatter'
import type { RequestProperties } from '@/lib/request-properties'
import { formatPrompt } from '@/lib/utils'
import EXECUTE_SQL_PROMPT from '@/templates/execute-sql-prompt.md'
import { getToolDefinition } from '@/tools/toolDefinitions'

import type { ResolvedState } from './request-state-resolver'

export class InstructionsBuilder {
    private readonly formatter: InstructionsFormatter
    private readonly guidelines: string

    constructor(guidelines: string, formatter?: InstructionsFormatter) {
        this.guidelines = guidelines
        this.formatter = formatter ?? new InstructionsFormatter()
    }

    async build(props: RequestProperties, state: ResolvedState): Promise<string> {
        const supportsInstructions = state.clientProfile.capabilities.supportsInstructions
        if (!supportsInstructions) {
            return ''
        }

        const { projectId } = props
        const resolvedProjectId = projectId || (await state.reqCtx.cache.get('projectId'))
        const [groupTypes, metadata] = await Promise.all([
            resolvedProjectId && hasScope(state.apiKeyScopes, 'group:read')
                ? state.context.stateManager.getOrFetchGroupTypes(resolvedProjectId)
                : undefined,
            state.context.stateManager.getEnvironmentPrompt(),
        ])

        const ctx: InstructionsContext = {
            ...(await this.buildContext(state)),
            groupTypes,
            metadata,
        }

        if (state.useSingleExec) {
            return this.formatter.buildExecInstructions(ctx)
        } else if (state.version === 2) {
            return this.formatter.buildV2Instructions(ctx)
        }
        return this.formatter.buildV1Instructions(metadata)
    }

    async buildContext(state: ResolvedState): Promise<InstructionsContext> {
        const tools = await Promise.all(
            state.allTools.map(async (t) => ({
                name: t.name,
                category: (await getToolDefinition(t.name, state.version)).category,
            }))
        )
        const queryTools = await Promise.all(
            state.allTools
                .filter((t) => t.name.startsWith('query-'))
                .map(async (t): Promise<QueryToolInfo> => {
                    const def = await getToolDefinition(t.name, state.version)
                    return {
                        name: t.name,
                        title: def.title,
                        ...(def.system_prompt_hint ? { systemPromptHint: def.system_prompt_hint } : {}),
                    }
                })
        )
        return {
            guidelines: this.guidelines,
            tools,
            queryTools,
            featureFlags: state.toolFeatureFlags,
        }
    }

    async buildExecToolEntry(state: ResolvedState, _props: RequestProperties): Promise<McpTool> {
        const supportsInstructions = state.clientProfile.capabilities.supportsInstructions
        const ctx = await this.buildContext(state)
        const commandReference = this.formatter.buildExecCommandReference(ctx, {
            stripEnvContext: supportsInstructions,
        })
        const ExecSchema = { command: { type: 'string', description: commandReference } }

        return {
            name: 'exec',
            title: 'Execute PostHog command',
            description: this.formatter.buildExecToolDescription(),
            inputSchema: { type: 'object', properties: ExecSchema, required: ['command'] },
        }
    }

    async buildExecCommandReference(state: ResolvedState): Promise<string> {
        const supportsInstructions = state.clientProfile.capabilities.supportsInstructions
        const ctx = await this.buildContext(state)
        return this.formatter.buildExecCommandReference(ctx, {
            stripEnvContext: supportsInstructions,
        })
    }

    buildExecToolDescription(): string {
        return this.formatter.buildExecToolDescription()
    }

    getGuidelines(): string {
        return this.guidelines
    }

    formatExecuteSqlDescription(): string {
        return formatPrompt(EXECUTE_SQL_PROMPT, { guidelines: this.guidelines.trim() })
    }
}
