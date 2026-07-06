import { IconActivity, IconSupport, IconThumbsUp } from '@posthog/icons'

/**
 * Sandbox-runtime slash command registry. Deliberately separate from the Max scene's
 * `MAX_SLASH_COMMANDS` (which types `name` as the `SlashCommandName` enum and carries LangGraph-only
 * commands): `name` here is a plain string, and the set is the three the `open` endpoint executes
 * server-side (`/usage`, `/feedback`, `/ticket`). `/init` and `/remember` stay LangGraph-only.
 */
export interface SurfaceSlashCommand {
    name: string
    arg?: `[${string}]`
    description: string
    icon: JSX.Element
    /** If true, only offered while the conversation is idle (not streaming). */
    requiresIdle?: boolean
}

export const SANDBOX_SLASH_COMMANDS: SurfaceSlashCommand[] = [
    {
        name: '/usage',
        description: 'View AI credit usage for this conversation and billing period',
        icon: <IconActivity />,
    },
    {
        name: '/feedback',
        arg: '[your feedback]',
        description: 'Share feedback about your PostHog AI experience',
        icon: <IconThumbsUp />,
    },
    {
        name: '/ticket',
        description: 'Create a support ticket with a summary of this conversation',
        icon: <IconSupport />,
        requiresIdle: true,
    },
]

/** The `/ticket` reply strings the frontend keys on to decide which ticket surface to render. */
export const TICKET_FIRST_MESSAGE_MARKER = "I'll help you create a support ticket"
export const TICKET_UPGRADE_MARKER = 'is available for customers on paid plans'

/**
 * Detect whether a message is a registered sandbox slash command — exact-or-`prefix + " "` match,
 * mirroring the backend `match_slash_command`. Used only to decide routing (a matched command must
 * route to `/open` on a born-sandbox conversation, never trigger a LangGraph→sandbox conversion).
 */
export function matchSandboxSlashCommand(content: string): SurfaceSlashCommand | null {
    const stripped = content.trim()
    for (const command of SANDBOX_SLASH_COMMANDS) {
        if (stripped === command.name || stripped.startsWith(command.name + ' ')) {
            return command
        }
    }
    return null
}
