// Sandbox-runtime slash command registry — the set the `open` endpoint executes server-side
// (`/usage`, `/feedback`, `/ticket`). Consumers (the Max scene) import from here, not from the deep
// `../slashCommands` path. See ../README.md for the tier model and ../AGENTS.md for the coupling rule.

export {
    SANDBOX_SLASH_COMMANDS,
    TICKET_FIRST_MESSAGE_MARKER,
    TICKET_UPGRADE_MARKER,
    matchSandboxSlashCommand,
    type SurfaceSlashCommand,
} from '../slashCommands'
