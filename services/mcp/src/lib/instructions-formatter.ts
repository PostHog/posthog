import type { GroupType } from '@/api/client'
import { MCP_INSTRUCTIONS_CHAR_BUDGET } from '@/lib/constants'
import {
    buildAvailableToolsBlock,
    buildDefinedGroupsBlock,
    buildQueryToolsBlock,
    buildToolDomainsBlock,
    buildToolDomainsCompact,
    type QueryToolInfo,
    type ToolInfo,
} from '@/lib/instructions'
import { formatPrompt } from '@/lib/utils'
import AGENT_FEEDBACK from '@/templates/sections/agent-feedback.md'
import ANALYSIS_ARTIFACTS from '@/templates/sections/analysis-artifacts.md'
import BASIC_FUNCTIONALITY from '@/templates/sections/basic-functionality.md'
import CATALOG_TRUST_DISCOVERY from '@/templates/sections/catalog-trust-discovery.md'
import CLI_DATA_DISCOVERY from '@/templates/sections/cli-data-discovery.md'
import CLI_ERROR_HANDLING from '@/templates/sections/cli-error-handling.md'
import CLI_EXAMPLES_CLAUDE from '@/templates/sections/cli-examples-claude.md'
import CLI_EXAMPLES from '@/templates/sections/cli-examples.md'
import CLI_RENDERING from '@/templates/sections/cli-rendering.md'
import CLI_SCHEMA_DRILLDOWN from '@/templates/sections/cli-schema-drilldown.md'
import CLI_SYNTAX from '@/templates/sections/cli-syntax.md'
import COMPACT_INSTRUCTIONS from '@/templates/sections/compact-instructions.md'
import ENTITY_SCHEMA_DISCOVERY from '@/templates/sections/entity-schema-discovery.md'
import ENV_CONTEXT from '@/templates/sections/env-context.md'
import EXAMPLES from '@/templates/sections/examples.md'
import EXEC_LEARN from '@/templates/sections/exec-learn.md'
import EXEC_TOOL_BLURB from '@/templates/sections/exec-tool-blurb.md'
import METRIC_DISCOVERY_COMPACT from '@/templates/sections/metric-discovery-compact.md'
import METRIC_DISCOVERY from '@/templates/sections/metric-discovery.md'
import NOTEBOOK_PYTHON from '@/templates/sections/notebook-python.md'
import RETRIEVING_DATA from '@/templates/sections/retrieving-data.md'
import SCHEMA_WORKFLOW from '@/templates/sections/schema-workflow.md'
import TOOL_SEARCH from '@/templates/sections/tool-search.md'
import URL_PATTERNS from '@/templates/sections/url-patterns.md'
import { type ExecHelpEntry, LEARN_COMMAND_LINE } from '@/tools/exec-help'

export interface InstructionsContext {
    guidelines: string
    groupTypes?: GroupType[] | undefined
    metadata?: string | undefined
    /** `metadata` without the product/integration context lines, for the claude.ai
     *  exec command reference, which counts against the ~16 KiB registry cap on the
     *  serialized inputSchema. Falls back to `metadata` when unset. */
    metadataCompact?: string | undefined
    tools?: ToolInfo[] | undefined
    queryTools?: QueryToolInfo[] | undefined
    /** Whether `render-ui` is actually available to this client (i.e. the client is
     *  an MCP Apps host). Gates the CLI rendering section so it never reaches clients —
     *  like Claude Code — that can't mount the iframe. */
    renderUiEnabled?: boolean | undefined
    /** Whether the notebook cell tools (`notebooks-add-cell` and friends) are
     *  advertised to this client. Gates the Python-in-a-notebook section so we never
     *  tell an agent to put its analysis in a cell type it can't create. */
    notebookCellsEnabled?: boolean | undefined
}

/**
 * Composes MCP instruction prompts for the two client modes (tools-mode and
 * single-exec). Each mode declares an ordered list of subprompts under
 * `services/mcp/src/templates/sections/`; subprompts that appear in multiple
 * modes live in a single file, so prose can't drift.
 */
export class InstructionsFormatter {
    /** Artifact-choice guidance: notebook vs dashboard vs insight, plus the
     *  Python-goes-in-a-cell rule when the notebook cell tools are available. */
    private artifactSections(ctx: InstructionsContext): string[] {
        return [ANALYSIS_ARTIFACTS, ...(ctx.notebookCellsEnabled ? [NOTEBOOK_PYTHON] : [])]
    }

    /** Build the system prompt for tools-mode clients (each tool registered separately). */
    buildToolsInstructions(ctx: InstructionsContext): string {
        return this.compose(
            [
                BASIC_FUNCTIONALITY,
                TOOL_SEARCH,
                METRIC_DISCOVERY,
                RETRIEVING_DATA,
                SCHEMA_WORKFLOW,
                CATALOG_TRUST_DISCOVERY,
                ...this.artifactSections(ctx),
                ENV_CONTEXT,
                URL_PATTERNS,
                AGENT_FEEDBACK,
                EXAMPLES,
            ],
            ctx,
            { compact: false }
        )
    }

    /** Build the compact `instructions` payload for single-exec clients. Everything
     *  but the tool-domain index — env context included — lives on the exec tool's
     *  `command` parameter description (`buildExecCommandReference`), because this
     *  payload is hard-capped at {@link MCP_INSTRUCTIONS_CHAR_BUDGET} by Claude Code
     *  and the command description is not.
     *
     *  Rendered optimistically, then re-rendered against the measured overflow if it
     *  doesn't fit — the index is the only part that can shrink. Measuring the overflow
     *  rather than the surround keeps the arithmetic exact: both renders carry a
     *  non-empty index, so they share a byte-identical surround, and shrinking the index
     *  by N shrinks the payload by exactly N. (Sizing an index-less render instead
     *  overshoots, because `formatPrompt` trims the trailing separator the real payload
     *  keeps.) Enforced by the budget test in `instructions-formatter-snapshot.test.ts`. */
    buildExecInstructions(ctx: InstructionsContext): string {
        const rendered = this.compose([COMPACT_INSTRUCTIONS], ctx, { compact: true })
        const overflow = rendered.length - MCP_INSTRUCTIONS_CHAR_BUDGET
        if (overflow <= 0) {
            return rendered
        }
        const domains = buildToolDomainsCompact(ctx.tools ?? [])
        return this.compose([COMPACT_INSTRUCTIONS], ctx, {
            compact: true,
            toolDomainsMaxChars: domains.length - overflow,
        })
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
    buildClaudeExecHelpEntries(ctx: InstructionsContext): ExecHelpEntry[] {
        const entries: ExecHelpEntry[] = [
            {
                id: 'analytics',
                kind: 'guide',
                title: 'Analytics',
                description:
                    'Query or analyze PostHog data; governed metrics, certified tables, and verified joins live in the catalog.',
                content: this.compose(
                    [
                        METRIC_DISCOVERY,
                        RETRIEVING_DATA,
                        SCHEMA_WORKFLOW,
                        CATALOG_TRUST_DISCOVERY,
                        ...this.artifactSections(ctx),
                        EXAMPLES,
                    ],
                    ctx,
                    { compact: false }
                ),
            },
        ]

        if (ctx.renderUiEnabled) {
            entries.push({
                id: 'visualizations',
                kind: 'guide',
                title: 'Visualizations',
                description: 'Create or render a visualization.',
                content: this.compose([CLI_RENDERING], ctx, { compact: false }),
            })
        }

        // URL rules are task-specific and load on demand instead of consuming Claude's capped input schema.
        entries.push({
            id: 'urls',
            kind: 'guide',
            title: 'URL patterns',
            description: 'Load before writing any PostHog app link or URL.',
            content: this.compose([URL_PATTERNS], ctx, { compact: false }),
        })

        entries.push({
            id: 'feedback',
            kind: 'guide',
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
    buildClaudeExecCommandReference(ctx: InstructionsContext): string {
        const helpEntries = this.buildClaudeExecHelpEntries(ctx)
        const helpTopics = helpEntries.map((entry) => `- ${entry.id}: ${entry.description}`).join('\n')
        const helpSection = formatPrompt(EXEC_LEARN, { help_topics: helpTopics })
        const renderCtx: InstructionsContext = {
            guidelines: ctx.guidelines,
            metadata: ctx.metadataCompact ?? ctx.metadata,
            groupTypes: ctx.groupTypes,
            tools: ctx.tools,
        }

        return this.compose(
            [
                CLI_SYNTAX,
                helpSection,
                METRIC_DISCOVERY_COMPACT,
                CLI_SCHEMA_DRILLDOWN,
                CLI_DATA_DISCOVERY,
                CLI_EXAMPLES_CLAUDE,
                CLI_ERROR_HANDLING,
                BASIC_FUNCTIONALITY,
                TOOL_SEARCH,
                ENV_CONTEXT,
            ],
            renderCtx,
            {
                compact: false,
                compactToolDomains: true,
                extraCommands: LEARN_COMMAND_LINE,
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
        opts: { stripEnvContext: boolean; keepEnvContext?: boolean }
    ): string {
        const sections = [
            CLI_SYNTAX,
            METRIC_DISCOVERY,
            CLI_SCHEMA_DRILLDOWN,
            CLI_DATA_DISCOVERY,
            CLI_EXAMPLES,
            CLI_ERROR_HANDLING,
            ...(ctx.renderUiEnabled ? [CLI_RENDERING] : []),
            BASIC_FUNCTIONALITY,
            TOOL_SEARCH,
            RETRIEVING_DATA,
            SCHEMA_WORKFLOW,
            CATALOG_TRUST_DISCOVERY,
            ...this.artifactSections(ctx),
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
        opts: {
            compact: boolean
            compactToolDomains?: boolean
            extraCommands?: string
            /** Character budget for the domain index; it collapses sub-families to fit. */
            toolDomainsMaxChars?: number
        }
    ): string {
        const renderToolDomains =
            opts.compact || opts.compactToolDomains
                ? (tools: ToolInfo[]) => buildToolDomainsCompact(tools, opts.toolDomainsMaxChars)
                : buildToolDomainsBlock
        // `{query_tools}` only appears in non-compact sections (the exec command
        // reference and tools-mode instructions); compact mode surfaces queries
        // via the single `query` tool domain instead.
        const vars = {
            guidelines: ctx.guidelines.trim(),
            available_tools: buildAvailableToolsBlock(ctx.renderUiEnabled),
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
