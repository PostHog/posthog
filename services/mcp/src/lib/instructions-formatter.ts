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
import CLI_CODE_EXECUTION_FAST_PATH from '@/templates/sections/cli-code-execution-fast-path.md'
import CLI_CODE_EXECUTION_TYPES from '@/templates/sections/cli-code-execution-types.md'
import CLI_CODE_EXECUTION from '@/templates/sections/cli-code-execution.md'
import CLI_DATA_DISCOVERY from '@/templates/sections/cli-data-discovery.md'
import CLI_ERROR_HANDLING from '@/templates/sections/cli-error-handling.md'
import CLI_EXAMPLES from '@/templates/sections/cli-examples.md'
import CLI_RENDERING from '@/templates/sections/cli-rendering.md'
import CLI_SCHEMA_DRILLDOWN from '@/templates/sections/cli-schema-drilldown.md'
import CLI_SYNTAX from '@/templates/sections/cli-syntax.md'
import CF_CHEAT_SHEET_RAW from '@/templates/sections/code-first/cheat-sheet.md'
import CF_DISCOVERY from '@/templates/sections/code-first/discovery.md'
import CF_ERROR_HANDLING from '@/templates/sections/code-first/error-handling.md'
import CF_EXEC_TOOL_BLURB from '@/templates/sections/code-first/exec-tool-blurb.md'
import CF_PLAN_APPLY from '@/templates/sections/code-first/plan-apply.md'
import CF_RENDERING from '@/templates/sections/code-first/rendering.md'
import CF_RETRIEVING_DATA from '@/templates/sections/code-first/retrieving-data.md'
import CF_SQL from '@/templates/sections/code-first/sql.md'
import CF_TRANSCRIPTS from '@/templates/sections/code-first/transcripts.md'
import CF_VERBS from '@/templates/sections/code-first/verbs.md'
import COMPACT_INSTRUCTIONS from '@/templates/sections/compact-instructions.md'
import ENTITY_SCHEMA_DISCOVERY from '@/templates/sections/entity-schema-discovery.md'
import ENV_CONTEXT from '@/templates/sections/env-context.md'
import EXAMPLES from '@/templates/sections/examples.md'
import EXEC_TOOL_BLURB from '@/templates/sections/exec-tool-blurb.md'
import RETRIEVING_DATA from '@/templates/sections/retrieving-data.md'
import SCHEMA_WORKFLOW from '@/templates/sections/schema-workflow.md'
import TOOL_SEARCH from '@/templates/sections/tool-search.md'
import URL_PATTERNS from '@/templates/sections/url-patterns.md'

/**
 * Availability level of the code-execution exec verbs (spec §4.2/§4.4). All
 * flag-on levels advertise `types`/`run`/`apply`/`sql` — the dispatcher
 * accepts every verb wherever the flag is on. `full` documents full script
 * execution; `fast-path` documents `run` restricted to single-call scripts
 * (no sandbox executor on this process, so anything else returns a targeted
 * error); `off` (or unset) hides the sections entirely — the flag is off.
 */
export type CodeExecutionLevel = 'off' | 'fast-path' | 'full'

// Template comments (curation notes, provenance) are for template maintainers,
// not the model — strip them so they never spend prompt budget.
const CF_CHEAT_SHEET = CF_CHEAT_SHEET_RAW.replace(/<!--[\s\S]*?-->\s*/g, '')

export interface InstructionsContext {
    guidelines: string
    groupTypes?: GroupType[] | undefined
    metadata?: string | undefined
    tools?: ToolInfo[] | undefined
    queryTools?: QueryToolInfo[] | undefined
    /** Resolved tool feature flags from `resolveToolFeatureFlags`. Used to gate
     *  prompt sections whose corresponding tool is flag-gated. */
    featureFlags?: EvaluatedFlags | undefined
    /** Whether `render-ui` is actually available to this client (i.e. the client is
     *  an MCP Apps host). Gates the CLI rendering section so it never reaches clients —
     *  like Claude Code — that can't mount the iframe. */
    renderUiEnabled?: boolean | undefined
    /** Availability of the code-execution exec verbs. Gates their command-reference
     *  sections so the advertised command set always matches what this process's
     *  dispatcher accepts (spec §4.4). */
    codeExecution?: CodeExecutionLevel | undefined
    /** The `mcp-code-first` flag (spec §4.6 Phase 3): swaps the exec blurb and
     *  command reference to the code-first variant, where legacy verbs disappear
     *  and TypeScript against `@posthog/sdk` is the one documented modality.
     *  Only takes effect at `codeExecution: 'full'` — the code-first prose
     *  documents unrestricted scripts, so anywhere the sandbox executor is
     *  absent the legacy arm keeps serving even with the flag on. */
    codeFirstEnabled?: boolean | undefined
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

    /** Build the top-level description of the `posthog:exec` tool. Callers with
     *  no context (the CLI's vendored help) get the legacy blurb. */
    buildExecToolDescription(ctx?: InstructionsContext): string {
        if (ctx && this.codeFirstArm(ctx)) {
            return CF_EXEC_TOOL_BLURB.trim()
        }
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
     *  payload to the model (Claude web/desktop): it retains the env-context
     *  (project metadata, group types) here even though `stripEnvContext` is
     *  set, so it still reaches the agent.
     *
     *  SIZE BUDGET: the serialized exec tool entry must stay under 32,600 chars —
     *  clients (e.g. Claude web/desktop) silently drop tools past ~32,768, which
     *  breaks the entire MCP for them. Enforced by the budget test in
     *  `tests/unit/instructions-formatter-snapshot.test.ts`; when adding prose
     *  here or to the section templates, shrink elsewhere to stay under. */
    buildExecCommandReference(
        ctx: InstructionsContext,
        opts: { stripEnvContext: boolean; keepEnvContext?: boolean }
    ): string {
        const sections = this.codeFirstArm(ctx) ? this.codeFirstSections(ctx) : this.legacySections(ctx)
        const renderCtx: InstructionsContext = opts.stripEnvContext
            ? {
                  guidelines: ctx.guidelines,
                  queryTools: ctx.queryTools,
                  featureFlags: ctx.featureFlags,
                  ...(opts.keepEnvContext ? { metadata: ctx.metadata, groupTypes: ctx.groupTypes } : {}),
              }
            : { ...ctx, tools: undefined }
        // Tool domains are temporarily omitted from the command reference while we
        // probe claude.ai's per-tool size cap (it silently drops oversized entries);
        // agents still discover domains at runtime via the `search` command, and
        // `instructions`-honoring clients keep the compact domain index there.
        return this.compose(sections, renderCtx, { compact: false })
    }

    /** Whether to render the code-first arm (spec §4.4/§4.6 Phase 3). The arm
     *  documents unrestricted scripts as THE interface, so it additionally
     *  requires the `full` availability level: with the flag on but no sandbox
     *  executor (`fast-path` level), the legacy arm keeps serving — the same
     *  conjunction the exec dispatcher applies, so served instructions and
     *  dispatch behavior can never disagree. */
    private codeFirstArm(ctx: InstructionsContext): boolean {
        return ctx.codeFirstEnabled === true && ctx.codeExecution === 'full'
    }

    /** The pre-code-first command reference: JSON-schema discovery with per-tool
     *  `call`, plus the flag-gated code-execution sections. Every byte here is
     *  pinned by the checked-in snapshots — the A/B against the code-first arm
     *  is only meaningful while this arm stays untouched. */
    private legacySections(ctx: InstructionsContext): string[] {
        return [
            CLI_SYNTAX,
            ...this.codeExecutionSections(ctx.codeExecution),
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
    }

    /** The code-first command reference (spec §4.4): one modality — TypeScript
     *  against `@posthog/sdk` — so the JSON-schema-compensation sections
     *  (drill-down, tool search, `call` examples) are cut and replaced by the
     *  verb table, cheat sheet, discovery/plan/sql sections, and worked
     *  transcripts. Data-taxonomy prose is shared verbatim with the legacy arm;
     *  it is orthogonal to API-surface discovery. */
    private codeFirstSections(ctx: InstructionsContext): string[] {
        return [
            CF_VERBS,
            CF_CHEAT_SHEET,
            CF_DISCOVERY,
            CF_PLAN_APPLY,
            CF_SQL,
            CLI_DATA_DISCOVERY,
            CF_ERROR_HANDLING,
            ...(ctx.renderUiEnabled ? [CF_RENDERING] : []),
            BASIC_FUNCTIONALITY,
            CF_RETRIEVING_DATA,
            ENV_CONTEXT,
            URL_PATTERNS,
            ...(this.agentFeedbackEnabled(ctx.featureFlags) ? [AGENT_FEEDBACK] : []),
            CF_TRANSCRIPTS,
        ]
    }

    /** Command-reference sections for the code-execution verbs, by availability
     *  level: the discovery core (`types`/`sql`) ships whenever the flag is on;
     *  the script-execution section comes in a full-sandbox and a fast-path-only
     *  variant so the documented `run` capability always matches what this
     *  process can actually execute (spec §4.2/§4.4). */
    private codeExecutionSections(level: CodeExecutionLevel | undefined): string[] {
        switch (level) {
            case 'full':
                return [CLI_CODE_EXECUTION_TYPES, CLI_CODE_EXECUTION]
            case 'fast-path':
                return [CLI_CODE_EXECUTION_TYPES, CLI_CODE_EXECUTION_FAST_PATH]
            default:
                return []
        }
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
        const vars = {
            guidelines: ctx.guidelines.trim(),
            defined_groups: buildDefinedGroupsBlock(ctx.groupTypes),
            metadata: ctx.metadata?.trim() ?? '',
            tool_domains: ctx.tools ? renderToolDomains(ctx.tools) : '',
            query_tools: ctx.queryTools ? buildQueryToolsBlock(ctx.queryTools) : '',
            entity_schema_discovery: ENTITY_SCHEMA_DISCOVERY.trim(),
        }
        const body = sections
            .map((s) => s.trim())
            .filter((s) => s.length > 0)
            .join('\n\n')
        return formatPrompt(body, vars)
    }
}
