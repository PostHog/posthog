import * as fs from 'node:fs/promises'
import * as path from 'node:path'

const START_MARKER = '<!-- posthog-cli-api:start -->'
const END_MARKER = '<!-- posthog-cli-api:end -->'

export const AGENTS_MD_SNIPPET = `${START_MARKER}
## PostHog

Use \`posthog-cli api\` for all PostHog-related queries and operations from this repository. Prefer \`posthog-cli api\` over direct MCP tool calls whenever the CLI is available.

The \`posthog-cli api\` command group is experimental. If it reports that the command group is disabled, rerun commands with \`POSTHOG_CLI_EXPERIMENTAL_API=1\` in the environment or pass \`--experimental\` immediately after \`api\`.

You must follow this required progressive disclosure workflow for every PostHog task. Do not skip steps, even if you think you already know the right tool or schema.

1. Start by searching for the tool you need with \`posthog-cli api search <term>\` or list tools with \`posthog-cli api tools\`.
2. Inspect the expected input schema with \`posthog-cli api info <tool>\`. This \`info\` step is required before every \`call\`. Use \`posthog-cli api schema <tool> [field.path]\` to drill into nested fields when needed.
3. Try the tool with \`posthog-cli api call --json <tool> '<json>'\` so output can be piped to \`jq\` or saved to disk.

- Use \`posthog-cli api call --dry-run ...\` before mutations.
- Destructive tools require \`--confirm\`; only add it after verifying exact target IDs.
- Install PostHog agent skills with \`posthog-cli api skill list\` and \`posthog-cli api skill install <skill-id>\`.
${END_MARKER}`

function errorCode(error: unknown): unknown {
    return typeof error === 'object' && error !== null && 'code' in error
        ? (error as { code?: unknown }).code
        : undefined
}

export async function installAgentsMdSnippet(opts: { cwd?: string; filePath?: string } = {}): Promise<string> {
    const targetPath = path.resolve(opts.filePath ?? path.join(opts.cwd ?? process.cwd(), 'AGENTS.md'))
    let existing = ''
    try {
        existing = await fs.readFile(targetPath, 'utf-8')
    } catch (error) {
        if (errorCode(error) !== 'ENOENT') {
            throw error
        }
    }

    let next: string
    const start = existing.indexOf(START_MARKER)
    const end = existing.indexOf(END_MARKER)
    if (start !== -1 && end !== -1 && end > start) {
        next = `${existing.slice(0, start)}${AGENTS_MD_SNIPPET}${existing.slice(end + END_MARKER.length)}`
    } else if (existing.trim()) {
        next = `${existing.trimEnd()}\n\n${AGENTS_MD_SNIPPET}\n`
    } else {
        next = `${AGENTS_MD_SNIPPET}\n`
    }

    await fs.mkdir(path.dirname(targetPath), { recursive: true })
    await fs.writeFile(targetPath, next)
    return targetPath
}
