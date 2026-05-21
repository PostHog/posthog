import { hasScope } from '@/lib/api'
import type { QueryToolInfo } from '@/lib/instructions'
import { type InstructionsContext, InstructionsFormatter } from '@/lib/instructions-formatter'
import type { RequestProperties } from '@/lib/request-properties'
import { formatPrompt } from '@/lib/utils'
import EXECUTE_SQL_PROMPT from '@/templates/execute-sql-prompt.md'
import { getToolDefinition } from '@/tools/toolDefinitions'

import type { PreBuiltToolEntry, ResolvedState } from './protocol-types'

import guidelines from '@shared/guidelines.md'

const _guidelines = typeof guidelines === 'string' ? guidelines : ((guidelines as { default?: string })?.default ?? '')

export class InstructionsBuilder {
    private readonly formatter: InstructionsFormatter
    private readonly guidelines: string

    constructor(guidelinesOverride?: string, formatter?: InstructionsFormatter) {
        this.guidelines = guidelinesOverride ?? _guidelines
        this.formatter = formatter ?? new InstructionsFormatter()
    }

    async build(props: RequestProperties, state: ResolvedState): Promise<string> {
        const supportsInstructions = state.clientProfile.capabilities.supportsInstructions
        if (!supportsInstructions) return ''

        const { projectId } = props
        const resolvedProjectId = projectId || (await state.reqCtx.cache.get('projectId'))
        const [groupTypes, metadata] = await Promise.all([
            resolvedProjectId && hasScope(state.apiKeyScopes, 'group:read')
                ? state.context.stateManager.getOrFetchGroupTypes(resolvedProjectId)
                : undefined,
            state.context.stateManager.getEnvironmentPrompt(),
        ])

        const ctx: InstructionsContext = {
            ...this.buildContext(state),
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

    buildContext(state: ResolvedState): InstructionsContext {
        return {
            guidelines: this.guidelines,
            tools: state.allTools.map((t) => ({
                name: t.name,
                category: getToolDefinition(t.name, state.version).category,
            })),
            queryTools: state.allTools
                .filter((t) => t.name.startsWith('query-'))
                .map((t) => {
                    const def = getToolDefinition(t.name, state.version)
                    return {
                        name: t.name,
                        title: def.title,
                        ...(def.system_prompt_hint ? { systemPromptHint: def.system_prompt_hint } : {}),
                    } as QueryToolInfo
                }),
            featureFlags: state.toolFeatureFlags,
        }
    }

    buildExecToolEntry(state: ResolvedState, props: RequestProperties): PreBuiltToolEntry {
        const supportsInstructions = state.clientProfile.capabilities.supportsInstructions
        const ctx = this.buildContext(state)
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

    buildExecCommandReference(state: ResolvedState): string {
        const supportsInstructions = state.clientProfile.capabilities.supportsInstructions
        const ctx = this.buildContext(state)
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
