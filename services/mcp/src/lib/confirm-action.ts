import type { Context } from '@/tools/types'

export class ConfirmationDeclinedError extends Error {
    constructor(message: string) {
        super(message)
        this.name = 'ConfirmationDeclinedError'
    }
}

export class ConfirmationUnsupportedError extends Error {
    constructor(message: string, options?: { cause?: unknown }) {
        super(message)
        this.name = 'ConfirmationUnsupportedError'
        if (options?.cause !== undefined) {
            // Assigned manually to stay compatible with TS libs that don't surface the
            // ES2022 `Error(message, { cause })` constructor signature.
            ;(this as Error & { cause?: unknown }).cause = options.cause
        }
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
            `This action requires manual user confirmation via the MCP client, but the elicitation request failed (${reason}). The client may not implement elicitation, or the request failed transiently. Use the PostHog web UI to make this change instead.`,
            { cause: error }
        )
    }

    if (result.action !== 'accept') {
        throw new ConfirmationDeclinedError(`User did not accept the action (${result.action}); no changes were made.`)
    }
}
