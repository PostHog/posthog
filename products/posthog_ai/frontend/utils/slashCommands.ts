import type { AgentCommand } from '../types/wireTypes'

export type AppCommandName = 'btw' | 'good' | 'bad' | 'feedback' | 'usage' | 'ticket'

export interface SlashCommand {
    /** Without the leading slash. */
    name: string
    description: string
    hint?: string
    /** `app` commands run in the browser; `agent` commands go to the agent as prompt text. */
    source: 'app' | 'agent'
}

export interface AppCommand extends SlashCommand {
    name: AppCommandName
    source: 'app'
    /** Set when the command needs text after its name. The value is the error shown when it is missing. */
    requiredInputError?: string
    /** Shown when the command is typed on a run that does not offer it. */
    unavailableError?: string
}

export const APP_COMMANDS: AppCommand[] = [
    {
        name: 'btw',
        description: 'Ask a quick side question without interrupting the conversation',
        hint: 'your question',
        source: 'app',
        requiredInputError: 'Add a question after /btw',
        unavailableError: 'Side questions only work while a Claude run is live',
    },
    { name: 'good', description: 'Send positive feedback', hint: 'optional comment', source: 'app' },
    { name: 'bad', description: 'Send negative feedback', hint: 'optional comment', source: 'app' },
    {
        name: 'feedback',
        description: 'Send feedback about PostHog AI',
        hint: 'your feedback',
        source: 'app',
        requiredInputError: 'Add your feedback after /feedback. To rate without a comment, use /good or /bad.',
    },
    { name: 'usage', description: 'Show token usage and cost for this run', source: 'app' },
    { name: 'ticket', description: 'Open a support ticket about this task', source: 'app' },
]

const APP_COMMANDS_BY_NAME: ReadonlyMap<string, AppCommand> = new Map(APP_COMMANDS.map((c) => [c.name, c]))

export function getAppCommand(name: string): AppCommand | undefined {
    return APP_COMMANDS_BY_NAME.get(name)
}

// The agent advertises its harness built-ins next to skills, with no field that tells them apart. These
// built-ins act on a local terminal or repo, or duplicate an app command, so they are hidden by name.
// Everything else the agent advertises (skills) stays visible, as do `clear` and `compact`.
const HIDDEN_AGENT_COMMANDS: ReadonlySet<string> = new Set([
    'add-dir',
    'agents',
    'batch',
    'bug',
    'claude-api',
    'config',
    'context',
    'cost',
    'debug',
    'doctor',
    'export',
    'extra-usage',
    'fewer-permission-prompts',
    'goal',
    'heapdump',
    'help',
    'hooks',
    'ide',
    'init',
    'insights',
    'install-github-app',
    'keybindings-help',
    'login',
    'logout',
    'loop',
    'mcp',
    'memory',
    'model',
    'output-style:new',
    'permissions',
    'plugin',
    'pr-comments',
    'privacy-settings',
    'release-notes',
    'resume',
    'review',
    'rewind',
    'sandbox',
    'schedule',
    'security-review',
    'simplify',
    'status',
    'statusline',
    'terminal-setup',
    'todos',
    'update-config',
    'upgrade',
    'vim',
])

export function isVisibleAgentCommand(name: string): boolean {
    return !HIDDEN_AGENT_COMMANDS.has(name) && !name.startsWith('mcp:')
}

/** App commands first, then the visible agent commands. An app command wins a name clash. */
export function buildSlashCommands(appCommands: AppCommand[], agentCommands: AgentCommand[]): SlashCommand[] {
    const names = new Set<string>(appCommands.map((c) => c.name))
    const visibleAgentCommands: SlashCommand[] = []
    for (const command of agentCommands) {
        if (names.has(command.name) || !isVisibleAgentCommand(command.name)) {
            continue
        }
        names.add(command.name)
        visibleAgentCommands.push({ ...command, source: 'agent' })
    }
    return [...appCommands, ...visibleAgentCommands]
}

/**
 * The commands to suggest for a draft. Suggests only while the draft is a lone `/name` token, so the menu
 * closes once the user types a space to add arguments. Name-prefix matches rank first.
 */
export function filterSlashCommands(commands: SlashCommand[], draft: string): SlashCommand[] {
    const match = /^\/(\S*)$/.exec(draft)
    if (!match) {
        return []
    }
    const query = match[1].toLowerCase()
    const prefix: SlashCommand[] = []
    const contains: SlashCommand[] = []
    for (const command of commands) {
        const name = command.name.toLowerCase()
        if (name.startsWith(query)) {
            prefix.push(command)
        } else if (name.includes(query) || command.description.toLowerCase().includes(query)) {
            contains.push(command)
        }
    }
    return [...prefix, ...contains]
}

export function parseSlashCommand(text: string): { name: string; args: string } | null {
    const match = /^\/(\S+)(?:\s+([\s\S]*))?$/.exec(text.trim())
    return match ? { name: match[1], args: (match[2] ?? '').trim() } : null
}
