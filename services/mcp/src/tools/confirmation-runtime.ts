/**
 * Runtime for the YAML `confirmation` paradigm. Generated handlers call
 * `requestConfirmation()` at the top; this module owns the
 * elicit-availability check, the runtime error fallback, and the canned
 * tool-result shapes for the short-circuit outcomes.
 */

import { ElicitationNotSupportedError } from '@/hono/session-bus'

import type { ConfirmationBuilder } from './confirmation-builders'
import type { Context } from './types'

export interface RequestConfirmationOptions<P = Record<string, unknown>> {
    /** Static prompt with `{paramName}` placeholders. Mutually exclusive with `builder`. */
    message?: string
    /** Dynamic prompt builder. Mutually exclusive with `message`. */
    builder?: ConfirmationBuilder<P>
    /** What to do when the client doesn't support elicitation. */
    onNoElicit: 'allow' | 'deny'
    /** Human-readable action name surfaced in the deny / cancel messages. */
    actionLabel?: string
}

export type ConfirmationOutcome =
    | { kind: 'accepted' }
    | { kind: 'allowed-no-elicit' }
    | { kind: 'denied-no-elicit'; result: ToolErrorResult }
    | { kind: 'cancelled'; result: ToolErrorResult }

interface ToolErrorResult {
    content: Array<{ type: 'text'; text: string }>
    isError: true
}

export async function requestConfirmation<P extends Record<string, unknown>>(
    context: Context,
    params: P,
    options: RequestConfirmationOptions<P>
): Promise<ConfirmationOutcome> {
    const actionLabel = options.actionLabel ?? 'this action'

    // `requestInput` is the universal seam — works on both 2025-06-18 (where
    // it delegates to elicit) and 2026-07-28 (where it throws an
    // InputRequiredSignal the dispatcher catches). Undefined means no
    // capability available; fall back per policy.
    if (!context.requestInput) {
        return noElicitOutcome(options.onNoElicit, actionLabel)
    }

    const prompt = await resolvePrompt(params, context, options)

    let elicitResult
    try {
        elicitResult = await context.requestInput({
            key: 'confirm',
            message: prompt,
            // Empty schema → clients render just the action buttons.
            // The protocol-level `action` field is the explicit-intent signal;
            // an extra "tick to confirm" checkbox would be friction without
            // security value (a client that auto-accepts will auto-tick too).
            requestedSchema: {
                type: 'object',
                properties: {},
            },
        })
    } catch (error) {
        // Runtime capability mismatch — route to the same branch as missing-at-init.
        if (error instanceof ElicitationNotSupportedError) {
            return noElicitOutcome(options.onNoElicit, actionLabel)
        }
        throw error
    }

    if (elicitResult.action === 'accept') {
        return { kind: 'accepted' }
    }
    return {
        kind: 'cancelled',
        result: {
            content: [
                {
                    type: 'text',
                    text: `${capitalize(actionLabel)} was not performed — the user ${
                        elicitResult.action === 'decline' ? 'declined' : 'cancelled'
                    } the confirmation prompt.`,
                },
            ],
            isError: true,
        },
    }
}

function noElicitOutcome(policy: 'allow' | 'deny', actionLabel: string): ConfirmationOutcome {
    if (policy === 'allow') {
        return { kind: 'allowed-no-elicit' }
    }
    return {
        kind: 'denied-no-elicit',
        result: {
            content: [
                {
                    type: 'text',
                    text:
                        `${capitalize(actionLabel)} requires a confirmation prompt that this MCP client does not support. ` +
                        `Either upgrade to a client that supports MCP elicitation, or perform the action via the PostHog web UI.`,
                },
            ],
            isError: true,
        },
    }
}

async function resolvePrompt<P extends Record<string, unknown>>(
    params: P,
    context: Context,
    options: RequestConfirmationOptions<P>
): Promise<string> {
    if (options.builder) {
        return await options.builder(params, context)
    }
    if (options.message) {
        return interpolate(options.message, params)
    }
    return `Confirm action?`
}

/** Missing keys stay as literal `{name}` so authors notice during smoke tests. */
function interpolate(template: string, params: Record<string, unknown>): string {
    return template.replace(/\{([a-zA-Z_][a-zA-Z0-9_]*)\}/g, (full, key: string) => {
        if (key in params) {
            const value = params[key]
            return value === null || value === undefined ? full : String(value)
        }
        return full
    })
}

function capitalize(text: string): string {
    if (!text) {
        return text
    }
    return text.charAt(0).toUpperCase() + text.slice(1)
}
