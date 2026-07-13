import type { QueryToolInfo, ToolInfo } from '@/lib/instructions'
import { type InstructionsContext, InstructionsFormatter } from '@/lib/instructions-formatter'
import { getToolDefinition } from '@/tools/toolDefinitions'
import type { Tool, ZodObjectAny } from '@/tools/types'

const AGENT_HELP_HEADER = `# PostHog API guide for agents

\`posthog-cli api\` is the agent-first interface to the PostHog API. It exposes the same tool surface as the PostHog MCP server's \`exec\` tool, so the reference below is the canonical guide for interacting with PostHog. Treat it as instructions to follow, not just documentation.

On top of the reference below, the CLI adds:

- \`posthog-cli api call --dry-run <tool> '<json>'\` — validate input against the tool schema without executing. Use it before any mutation.
- Destructive tools refuse to run without \`--confirm\`; add it only after verifying the exact target IDs.
- \`posthog-cli api skill list\` and \`posthog-cli api skill install <skill-id>\` — install PostHog agent skills into \`.agents/skills/\`. Before starting a PostHog task, check the skill list for a match; if one exists, install it, read its \`SKILL.md\`, and follow it — skills contain task-specific workflows that individual tools do not.
- \`posthog-cli api agents-md install [--path AGENTS.md]\` — install the PostHog steering snippet into a repository.
- \`posthog-cli api run --file <path>\` and \`run -\` (stdin) pass a script without shell-quoting TypeScript; \`run --yes\` applies a returned plan in the same invocation (scripted/CI use). \`types\` works without an API key; \`run\`/\`apply\` require one.`

const EXEC_INVOCATION_PATTERN = /posthog:exec\(\{\s*"command":\s*"((?:\\.|[^"\\])*)"\s*\}\)/g

function commandToCliInvocation(command: string): string {
    const braceIndex = command.indexOf('{')
    if (braceIndex === -1) {
        return `posthog-cli api ${command}`
    }
    return `posthog-cli api ${command.slice(0, braceIndex).trimEnd()} '${command.slice(braceIndex)}'`
}

/** The MCP templates document the exec surface as \`posthog:exec({ "command": "<cmd>" })\`
 *  tool calls. The CLI exposes the identical command strings as \`posthog-cli api <cmd>\`,
 *  so rewriting invocations (instead of forking the templates) keeps one source of truth. */
export function toCliSyntax(text: string): string {
    return text
        .replace(EXEC_INVOCATION_PATTERN, (_match, command: string) =>
            commandToCliInvocation(command.replace(/\\"/g, '"'))
        )
        .replace('### Using the `posthog` tool', '### Using `posthog-cli api`')
        .replace(
            'Pass CLI-style commands in the `command` parameter for all PostHog interactions.',
            'Pass CLI-style commands as arguments to `posthog-cli api` for all PostHog interactions.'
        )
}

/** Build the full agent-facing guide for \`posthog-cli api --agent-help\` from the same
 *  exec-tool templates the MCP server serves, including the tool-domain index and the
 *  query-tool catalog derived from the bundled tool registry (no network or auth needed). */
export function buildAgentHelp(tools: Tool<ZodObjectAny>[]): string {
    const formatter = new InstructionsFormatter()
    const toolInfos: ToolInfo[] = tools.map((tool) => ({
        name: tool.name,
        category: getToolDefinition(tool.name).category,
    }))
    const queryTools: QueryToolInfo[] = tools
        .filter((tool) => tool.name.startsWith('query-'))
        .map((tool) => {
            const definition = getToolDefinition(tool.name)
            return {
                name: tool.name,
                title: definition.title,
                ...(definition.system_prompt_hint ? { systemPromptHint: definition.system_prompt_hint } : {}),
            } as QueryToolInfo
        })

    // The CLI always ships the code-execution verbs (spec §4.8 — no feature
    // flag, no executor gating on the user's own machine), so the guide always
    // includes both code-execution sections.
    const ctx: InstructionsContext = { guidelines: '', tools: toolInfos, queryTools, codeExecution: 'full' }
    const sections = [
        AGENT_HELP_HEADER,
        formatter.buildExecToolDescription(),
        formatter.buildExecCommandReference(ctx, { stripEnvContext: false }),
    ]
    return toCliSyntax(sections.join('\n\n'))
}
