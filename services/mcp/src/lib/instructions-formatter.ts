import type { GroupType } from '@/api/client'
import {
    buildDefinedGroupsBlock,
    buildQueryToolsBlock,
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
import CLI_EXAMPLES_CLAUDE from '@/templates/sections/cli-examples-claude.md'
import CLI_EXAMPLES from '@/templates/sections/cli-examples.md'
import CLI_LEARN from '@/templates/sections/cli-learn.md'
import CLI_RENDERING from '@/templates/sections/cli-rendering.md'
import CLI_SCHEMA_DRILLDOWN from '@/templates/sections/cli-schema-drilldown.md'
import CLI_SYNTAX from '@/templates/sections/cli-syntax.md'
import COMPACT_INSTRUCTIONS from '@/templates/sections/compact-instructions.md'
import ENTITY_SCHEMA_DISCOVERY from '@/templates/sections/entity-schema-discovery.md'
import ENV_CONTEXT from '@/templates/sections/env-context.md'
import EXAMPLES from '@/templates/sections/examples.md'
import EXEC_LEARN from '@/templates/sections/exec-learn.md'
import EXEC_TOOL_BLURB from '@/templates/sections/exec-tool-blurb.md'
import RETRIEVING_DATA from '@/templates/sections/retrieving-data.md'
import SCHEMA_WORKFLOW from '@/templates/sections/schema-workflow.md'
import TOOL_SEARCH from '@/templates/sections/tool-search.md'
import URL_PATTERNS from '@/templates/sections/url-patterns.md'
import type { ExecLearnGuide } from '@/tools/exec-learn'

export interface InstructionsContext {
    guidelines: string
    groupTypes?: GroupType[] | undefined
    metadata?: string | undefined
    tools?: ToolInfo[] | undefined
    queryTools?: QueryToolInfo[] | undefined
    /** Whether `render-ui` is actually available to this client (i.e. the client is
     *  an MCP Apps host). Gates the CLI rendering section so it never reaches clients —
     *  like Claude Code — that can't mount the iframe. */
    renderUiEnabled?: boolean | undefined
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
                AGENT_FEEDBACK,
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

    /**
     * Build the optional guidance catalog used by Claude web/desktop. The
     * existing prompt sections remain the source of truth; only their delivery
     * moves from the advertised schema to `exec learn`.
     */
    buildClaudeExecLearnGuides(ctx: InstructionsContext): ExecLearnGuide[] {
        const entries: ExecLearnGuide[] = [
            {
                id: 'analytics',
                title: 'Analytics',
                description: 'Query or analyze PostHog data, metrics, and events.',
                content: this.compose([RETRIEVING_DATA, SCHEMA_WORKFLOW, EXAMPLES], ctx, { compact: false }),
            },
        ]

        if (ctx.renderUiEnabled) {
            entries.push({
                id: 'visualizations',
                title: 'Visualizations',
                description: 'Create or render a visualization.',
                content: this.compose([CLI_RENDERING], ctx, { compact: false }),
            })
        }

        entries.push({
            id: 'feedback',
            title: 'Feedback',
            description: 'Send feedback about PostHog.',
            content: this.compose([AGENT_FEEDBACK], ctx, { compact: false }),
        })

        return entries
    }

    /**
     * claude.ai's registry silently drops a tool whose serialized `inputSchema`
     * crosses ~16,384 chars. This reference lands in
     * `inputSchema.properties.command.description`, so keep routine tool-use
     * guidance inline and move only task-specific sections behind `learn <topic...>`.
     * Enforced by the budget test in `instructions-formatter-snapshot.test.ts`.
     */
    buildClaudeExecCommandReference(
        ctx: InstructionsContext,
        opts: { learnEnabled?: boolean; skillsEnabled?: boolean } = {}
    ): string {
        const learnEnabled = opts.learnEnabled ?? true
        const skillsEnabled = opts.skillsEnabled ?? true
        const learnGuides = this.buildClaudeExecLearnGuides(ctx)
        const learnGuideList = learnGuides.map((entry) => `- ${entry.id}: ${entry.description}`).join('\n')
        const learnSection = learnEnabled
            ? formatPrompt(EXEC_LEARN, {
                  help_topics: learnGuideList,
              })
            : undefined
        const renderCtx: InstructionsContext = {
            guidelines: ctx.guidelines,
            metadata: ctx.metadata,
            groupTypes: ctx.groupTypes,
            tools: ctx.tools,
        }

        return this.compose(
            [
                CLI_SYNTAX,
                ...(skillsEnabled ? [CLI_LEARN] : []),
                ...(learnSection ? [learnSection] : []),
                CLI_SCHEMA_DRILLDOWN,
                CLI_DATA_DISCOVERY,
                CLI_EXAMPLES_CLAUDE,
                CLI_ERROR_HANDLING,
                BASIC_FUNCTIONALITY,
                TOOL_SEARCH,
                ENV_CONTEXT,
                URL_PATTERNS,
            ],
            renderCtx,
            {
                compact: false,
                compactToolDomains: true,
                extraCommands: learnEnabled ? 'learn <topic...> - load one or more learning topics\n' : undefined,
            }
        )
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
     *  payload to the model (Claude web/desktop): it retains the env-context
     *  (project metadata, group types) here even though `stripEnvContext` is
     *  set, so it still reaches the agent.
     *
     *  Claude web/desktop uses `buildClaudeExecCommandReference` instead because
     *  its complete JSON schema has a smaller client-enforced size budget. */
    buildExecCommandReference(
        ctx: InstructionsContext,
        opts: { stripEnvContext: boolean; keepEnvContext?: boolean; learnEnabled?: boolean }
    ): string {
        const sections = [
            CLI_SYNTAX,
            ...((opts.learnEnabled ?? true) ? [CLI_LEARN] : []),
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
            AGENT_FEEDBACK,
            EXAMPLES,
        ]
        const renderCtx: InstructionsContext = opts.stripEnvContext
            ? {
                  guidelines: ctx.guidelines,
                  queryTools: ctx.queryTools,
                  ...(opts.keepEnvContext ? { metadata: ctx.metadata, groupTypes: ctx.groupTypes } : {}),
              }
            : { ...ctx, tools: undefined }
        // Tool domains are temporarily omitted from the command reference while we
        // probe claude.ai's per-tool size cap (it silently drops oversized entries);
        // agents still discover domains at runtime via the `search` command, and
        // `instructions`-honoring clients keep the compact domain index there.
        return this.compose(sections, renderCtx, { compact: false })
    }

    private compose(
        sections: string[],
        ctx: InstructionsContext,
        opts: { compact: boolean; compactToolDomains?: boolean; extraCommands?: string }
    ): string {
        const renderToolDomains =
            opts.compact || opts.compactToolDomains ? buildToolDomainsCompact : buildToolDomainsBlock
        // `{query_tools}` only appears in non-compact sections (the exec command
        // reference and tools-mode instructions); compact mode surfaces queries
        // via the single `query` tool domain instead.
        const vars = {
            guidelines: ctx.guidelines.trim(),
            defined_groups: buildDefinedGroupsBlock(ctx.groupTypes),
            metadata: ctx.metadata?.trim() ?? '',
            tool_domains: ctx.tools ? renderToolDomains(ctx.tools) : '',
            query_tools: ctx.queryTools ? buildQueryToolsBlock(ctx.queryTools) : '',
            entity_schema_discovery: ENTITY_SCHEMA_DISCOVERY.trim(),
            extra_commands: opts.extraCommands ?? '',
        }
        const body = sections
            .map((s) => s.trim())
            .filter((s) => s.length > 0)
            .join('\n\n')
        return formatPrompt(body, vars)
    }
}
