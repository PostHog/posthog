import type { GroupType } from '@/api/client'
import {
    buildDefinedGroupsBlock,
    buildQueryToolsBlock,
    buildToolDomainsBlock,
    buildToolDomainsCompact,
    type QueryToolInfo,
    type ToolInfo,
} from '@/lib/instructions'
import type { EvaluatedFlags } from '@/lib/posthog/flags'
import { formatPrompt } from '@/lib/utils'
import AGENT_FEEDBACK from '@/templates/sections/agent-feedback.md'
import BASIC_FUNCTIONALITY from '@/templates/sections/basic-functionality.md'
import CLI_DATA_DISCOVERY from '@/templates/sections/cli-data-discovery.md'
import CLI_ERROR_HANDLING from '@/templates/sections/cli-error-handling.md'
import CLI_EXAMPLES from '@/templates/sections/cli-examples.md'
import CLI_RENDERING from '@/templates/sections/cli-rendering.md'
import CLI_SCHEMA_DRILLDOWN from '@/templates/sections/cli-schema-drilldown.md'
import CLI_SYNTAX from '@/templates/sections/cli-syntax.md'
import COMPACT_INSTRUCTIONS from '@/templates/sections/compact-instructions.md'
import ENTITY_SCHEMA_DISCOVERY_INFOSCHEMA from '@/templates/sections/entity-schema-discovery-infoschema.md'
import ENTITY_SCHEMA_DISCOVERY_LEGACY from '@/templates/sections/entity-schema-discovery-legacy.md'
import ENV_CONTEXT from '@/templates/sections/env-context.md'
import EXAMPLES from '@/templates/sections/examples.md'
import EXEC_TOOL_BLURB from '@/templates/sections/exec-tool-blurb.md'
import RETRIEVING_DATA from '@/templates/sections/retrieving-data.md'
import SCHEMA_WORKFLOW from '@/templates/sections/schema-workflow.md'
import TOOL_SEARCH from '@/templates/sections/tool-search.md'
import URL_PATTERNS from '@/templates/sections/url-patterns.md'
import { SQL_SCHEMA_DISCOVERY_FEATURE_FLAG } from '@/tools/posthogAiTools/readDataWarehouseSchema'

export interface InstructionsContext {
    guidelines: string
    groupTypes?: GroupType[] | undefined
    metadata?: string | undefined
    tools?: ToolInfo[] | undefined
    queryTools?: QueryToolInfo[] | undefined
    /** Resolved tool feature flags from `resolveToolFeatureFlags`. Used to gate
     *  prompt sections whose corresponding tool is flag-gated. */
    featureFlags?: EvaluatedFlags | undefined
    /** Whether `render-ui` is actually available to this client (the `mcp-render-ui`
     *  flag is on AND the client is an MCP Apps host). Gates the CLI rendering section
     *  so it never reaches clients — like Claude Code — that can't mount the iframe. */
    renderUiEnabled?: boolean | undefined
}

/** Whether schema discovery should be routed through `system.information_schema.*`
 *  SQL (the `mcp-sql-schema-discovery` flag) instead of the `read-data-warehouse-schema`
 *  tool. Prompt-only: when on, no instruction names the tool, so the agent discovers
 *  tables/columns/relationships with SQL. The tool itself stays advertised either way. */
export function schemaDiscoveryViaSqlEnabled(featureFlags: EvaluatedFlags | undefined): boolean {
    return featureFlags?.[SQL_SCHEMA_DISCOVERY_FEATURE_FLAG] === true
}

/**
 * Composes MCP instruction prompts for the two client modes (tools-mode and
 * single-exec). Each mode declares an ordered list of subprompts under
 * `services/mcp/src/templates/sections/`; subprompts that appear in multiple
 * modes live in a single file, so prose can't drift.
 */
export class InstructionsFormatter {
    /** Build the system prompt for tools-mode clients (each tool registered separately). */
    buildToolsInstructions(ctx: InstructionsContext): string {
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
     *  `instructions` field), the env-related placeholders (metadata, group
     *  types, tool domains) resolve to empty strings to avoid duplication. The
     *  query-tool catalog is kept: in single-exec mode it lives here on the exec
     *  tool, not in `instructions` (which only carries the `query` tool domain).
     *
     *  `keepEnvContext` is the escape hatch for clients that report
     *  `supportsInstructions` but don't actually surface the `instructions`
     *  payload to the model (Claude web/desktop): it retains the full env-context
     *  (tool-domain index, project metadata, group types) here even though
     *  `stripEnvContext` is set, so it still reaches the agent. */
    buildExecCommandReference(
        ctx: InstructionsContext,
        opts: { stripEnvContext: boolean; keepEnvContext?: boolean }
    ): string {
        const sections = [
            CLI_SYNTAX,
            CLI_SCHEMA_DRILLDOWN,
            CLI_DATA_DISCOVERY,
            CLI_EXAMPLES,
            CLI_ERROR_HANDLING,
            ...(ctx.renderUiEnabled ? [CLI_RENDERING] : []),
            BASIC_FUNCTIONALITY,
            TOOL_SEARCH,
            RETRIEVING_DATA,
            SCHEMA_WORKFLOW,
            ENV_CONTEXT,
            URL_PATTERNS,
            ...(this.agentFeedbackEnabled(ctx.featureFlags) ? [AGENT_FEEDBACK] : []),
            EXAMPLES,
        ]
        const renderCtx: InstructionsContext = opts.stripEnvContext
            ? {
                  guidelines: ctx.guidelines,
                  queryTools: ctx.queryTools,
                  featureFlags: ctx.featureFlags,
                  ...(opts.keepEnvContext
                      ? { tools: ctx.tools, metadata: ctx.metadata, groupTypes: ctx.groupTypes }
                      : {}),
              }
            : ctx
        return this.compose(sections, renderCtx, { compact: false })
    }

    /** The agent-feedback section is only useful when the `agent-feedback` tool
     *  is reachable, which is governed by the `mcp-feedback-tool` flag evaluated
     *  in `resolveToolFeatureFlags`. */
    private agentFeedbackEnabled(featureFlags: EvaluatedFlags | undefined): boolean {
        return featureFlags?.['mcp-feedback-tool'] === true
    }

    private compose(sections: string[], ctx: InstructionsContext, opts: { compact: boolean }): string {
        const renderToolDomains = opts.compact ? buildToolDomainsCompact : buildToolDomainsBlock
        // `{query_tools}` only appears in non-compact sections (the exec command
        // reference and tools-mode instructions); compact mode surfaces queries
        // via the single `query` tool domain instead.
        const entitySchemaDiscovery = schemaDiscoveryViaSqlEnabled(ctx.featureFlags)
            ? ENTITY_SCHEMA_DISCOVERY_INFOSCHEMA
            : ENTITY_SCHEMA_DISCOVERY_LEGACY
        const vars = {
            guidelines: ctx.guidelines.trim(),
            defined_groups: buildDefinedGroupsBlock(ctx.groupTypes),
            metadata: ctx.metadata?.trim() ?? '',
            tool_domains: ctx.tools ? renderToolDomains(ctx.tools) : '',
            query_tools: ctx.queryTools ? buildQueryToolsBlock(ctx.queryTools) : '',
            entity_schema_discovery: entitySchemaDiscovery.trim(),
        }
        const body = sections
            .map((s) => s.trim())
            .filter((s) => s.length > 0)
            .join('\n\n')
        return formatPrompt(body, vars)
    }
}
