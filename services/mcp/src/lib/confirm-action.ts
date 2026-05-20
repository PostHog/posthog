import type { Context } from '@/tools/types'

export class ConfirmationDeclinedError extends Error {
    constructor(message: string) {
        super(message)
        this.name = 'ConfirmationDeclinedError'
    }
}

export class ConfirmationUnsupportedError extends Error {
    constructor(message: string) {
        super(message)
        this.name = 'ConfirmationUnsupportedError'
    }
}

export interface ConfirmActionInput {
    /** Short imperative title shown in the confirmation modal (e.g. "Enforce 2FA for organization"). */
    title: string
    /** Long-form description shown to the user — explain what changes and why it matters. */
    description: string
}

/**
 * Block a destructive action behind a manual user confirmation via MCP elicitation.
 *
 * Throws `ConfirmationDeclinedError` if the user declines or cancels.
 * Throws `ConfirmationUnsupportedError` if the client does not implement elicitation —
 * sensitive actions fail closed when the client cannot show a confirmation UI.
 */
export async function confirmAction(context: Context, input: ConfirmActionInput): Promise<void> {
    const message = `${input.title}\n\n${input.description}`

    let result
    try {
        result = await context.elicit({
            message,
            requestedSchema: {
                type: 'object',
                properties: {},
            },
        })
    } catch (error) {
        const reason = error instanceof Error ? error.message : String(error)
        throw new ConfirmationUnsupportedError(
            `This action requires manual user confirmation via the MCP client, but the client did not respond to an elicitation request (${reason}). Use the PostHog web UI to make this change instead.`
        )
    }

    if (result.action !== 'accept') {
        throw new ConfirmationDeclinedError(`User did not accept the action (${result.action}); no changes were made.`)
    }
}
