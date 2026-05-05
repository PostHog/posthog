import type { GroupType } from '@/api/client'
import {
    buildDefinedGroupsBlock,
    buildQueryToolsBlock,
    buildQueryToolsCompact,
    buildToolDomainsBlock,
    buildToolDomainsCompact,
    type QueryToolInfo,
    type ToolInfo,
} from '@/lib/instructions'
import { formatPrompt } from '@/lib/utils'
import AGENT_FEEDBACK from '@/templates/sections/agent-feedback.md'
import BASIC_FUNCTIONALITY from '@/templates/sections/basic-functionality.md'
import CLI_DATA_DISCOVERY from '@/templates/sections/cli-data-discovery.md'
import CLI_ERROR_HANDLING from '@/templates/sections/cli-error-handling.md'
import CLI_EXAMPLES from '@/templates/sections/cli-examples.md'
import CLI_SCHEMA_DRILLDOWN from '@/templates/sections/cli-schema-drilldown.md'
import CLI_SYNTAX from '@/templates/sections/cli-syntax.md'
import COMPACT_INSTRUCTIONS from '@/templates/sections/compact-instructions.md'
import ENV_CONTEXT from '@/templates/sections/env-context.md'
import EXAMPLES from '@/templates/sections/examples.md'
import EXEC_TOOL_BLURB from '@/templates/sections/exec-tool-blurb.md'
import LEGACY from '@/templates/sections/legacy.md'
import RETRIEVING_DATA from '@/templates/sections/retrieving-data.md'
import SCHEMA_WORKFLOW from '@/templates/sections/schema-workflow.md'
import TOOL_SEARCH from '@/templates/sections/tool-search.md'
import URL_PATTERNS from '@/templates/sections/url-patterns.md'

export interface InstructionsContext {
    guidelines: string
    groupTypes?: GroupType[] | undefined
    metadata?: string | undefined
    tools?: ToolInfo[] | undefined
    queryTools?: QueryToolInfo[] | undefined
    /** Resolved tool feature flags from `resolveToolFeatureFlags`. Used to gate
     *  prompt sections whose corresponding tool is flag-gated. */
    featureFlags?: Record<string, boolean> | undefined
}

/**
 * Composes MCP instruction prompts for the three client modes (legacy v1,
 * tools-mode v2, single-exec). Each mode declares an ordered list of
 * subprompts under `services/mcp/src/templates/sections/`; subprompts that
 * appear in multiple modes live in a single file, so prose can't drift.
 */
export class InstructionsFormatter {
    /** Build the legacy v1 instructions string. Appends `metadata` to the legacy
     *  section if provided. */
    buildV1Instructions(metadata?: string): string {
        const legacy = LEGACY.trim()
        if (!metadata) {
            return legacy
        }
        return `${legacy}\n\n${metadata}`
    }

    /** Build the system prompt for tools-mode clients (each tool registered separately). */
    buildV2Instructions(ctx: InstructionsContext): string {
        return this.compose(
            [
                BASIC_FUNCTIONALITY,
                TOOL_SEARCH,
                RETRIEVING_DATA,
                SCHEMA_WORKFLOW,
                ENV_CONTEXT,
                URL_PATTERNS,
                ...(this.agentFeedbackEnabled(ctx.featureFlags) ? [AGENT_FEEDBACK] : []),
                EXAMPLES,
            ],
            ctx,
            { compact: false }
        )
    }

    /** Build the compact `instructions` payload for single-exec clients (~2KB budget).
     *  The bulk of the system prompt lives on the exec tool's `command` parameter
     *  description (`buildExecCommandReference`) — this is just env + tool index. */
    buildExecInstructions(ctx: InstructionsContext): string {
        return this.compose([COMPACT_INSTRUCTIONS], ctx, { compact: true })
    }

    /** Build the top-level description of the `posthog:exec` tool. */
    buildExecToolDescription(): string {
        return EXEC_TOOL_BLURB.trim()
    }

    /** Build the `command` parameter description for the exec tool. When
     *  `stripEnvContext` is true (the client already received env via the
     *  `instructions` field), the env-related placeholders resolve to empty
     *  strings to avoid duplication. */
    buildExecCommandReference(ctx: InstructionsContext, opts: { stripEnvContext: boolean }): string {
        const sections = [
            CLI_SYNTAX,
            CLI_SCHEMA_DRILLDOWN,
            CLI_DATA_DISCOVERY,
            CLI_EXAMPLES,
            CLI_ERROR_HANDLING,
            BASIC_FUNCTIONALITY,
            TOOL_SEARCH,
            RETRIEVING_DATA,
            SCHEMA_WORKFLOW,
            ENV_CONTEXT,
            URL_PATTERNS,
            ...(this.agentFeedbackEnabled(ctx.featureFlags) ? [AGENT_FEEDBACK] : []),
            EXAMPLES,
        ]
        const renderCtx: InstructionsContext = opts.stripEnvContext ? { guidelines: ctx.guidelines } : ctx
        return this.compose(sections, renderCtx, { compact: false })
    }

    /** The agent-feedback section is only useful when the `agent-feedback` tool
     *  is reachable, which is governed by the `mcp-feedback-tool` flag evaluated
     *  in `resolveToolFeatureFlags`. */
    private agentFeedbackEnabled(featureFlags: Record<string, boolean> | undefined): boolean {
        return featureFlags?.['mcp-feedback-tool'] === true
    }

    private compose(sections: string[], ctx: InstructionsContext, opts: { compact: boolean }): string {
        const renderToolDomains = opts.compact ? buildToolDomainsCompact : buildToolDomainsBlock
        const renderQueryTools = opts.compact ? buildQueryToolsCompact : buildQueryToolsBlock
        const vars = {
            guidelines: ctx.guidelines.trim(),
            defined_groups: buildDefinedGroupsBlock(ctx.groupTypes),
            metadata: ctx.metadata?.trim() ?? '',
            tool_domains: ctx.tools ? renderToolDomains(ctx.tools) : '',
            query_tools: ctx.queryTools ? renderQueryTools(ctx.queryTools) : '',
        }
        const body = sections
            .map((s) => s.trim())
            .filter((s) => s.length > 0)
            .join('\n\n')
        return formatPrompt(body, vars)
    }
}
