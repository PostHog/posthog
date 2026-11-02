import { z } from 'zod'

const OPTION_ID_PATTERN = /^[a-z0-9][a-z0-9_-]{0,63}$/
const NOTE_MAX_LENGTH = 1000

export const DecisionOptionSchema = z.object({
    id: z.string().regex(OPTION_ID_PATTERN).describe('Stable id the agent branches on, such as "ship" or "hold".'),
    label: z.string().trim().min(1).max(100).describe('Short label the human sees.'),
    description: z.string().trim().max(300).optional().describe('What happens if the human picks this option.'),
})

export const DecisionRequestInputSchema = z.object({
    question: z
        .string()
        .trim()
        .min(1)
        .max(500)
        .describe('One question the human can answer without reading the transcript.'),
    options: z
        .array(DecisionOptionSchema)
        .min(2)
        .max(6)
        .refine((options) => new Set(options.map((option) => option.id)).size === options.length, {
            message: 'Option ids must be unique.',
        })
        .describe('The choices. The agent must handle every option, plus a decline and an expiry.'),
    context: z
        .string()
        .trim()
        .max(2000)
        .optional()
        .describe('Evidence the human needs to decide: what was found, what is at stake.'),
    expires_in_seconds: z
        .number()
        .int()
        .min(60)
        .max(7 * 24 * 60 * 60)
        .default(15 * 60)
        .describe(
            'How long the question stays answerable. An unanswered question expires and never defaults to an option.'
        ),
    idempotency_key: z
        .string()
        .min(1)
        .max(128)
        .optional()
        .describe('Repeat the same key to get the same request back after a retry or resume.'),
})

export type DecisionRequestInput = z.infer<typeof DecisionRequestInputSchema>

export type DecisionOutcome =
    | { outcome: 'answered'; option_id: string; note?: string }
    | { outcome: 'declined' }
    | { outcome: 'cancelled' }
    | { outcome: 'invalid'; reason: string }

export interface DecisionElicitationParams {
    mode: 'form'
    message: string
    requestedSchema: {
        type: 'object'
        properties: {
            choice: { type: 'string'; title: string; oneOf: Array<{ const: string; title: string }> }
            note: { type: 'string'; title: string; maxLength: number }
        }
        required: ['choice']
    }
}

export function buildDecisionElicitation(input: DecisionRequestInput): DecisionElicitationParams {
    return {
        mode: 'form',
        message: input.context ? `${input.question}\n\n${input.context}` : input.question,
        requestedSchema: {
            type: 'object',
            properties: {
                choice: {
                    type: 'string',
                    title: 'Decision',
                    oneOf: input.options.map((option) => ({
                        const: option.id,
                        title: option.description ? `${option.label}: ${option.description}` : option.label,
                    })),
                },
                note: { type: 'string', title: 'Note for the agent (optional)', maxLength: NOTE_MAX_LENGTH },
            },
            required: ['choice'],
        },
    }
}

const ElicitResultSchema = z.object({
    action: z.enum(['accept', 'decline', 'cancel']),
    content: z.record(z.string(), z.unknown()).optional(),
})

/** The client renders the form, so an accepted answer is still untrusted input until it matches a requested option. */
export function parseDecisionResponse(input: DecisionRequestInput, response: unknown): DecisionOutcome {
    const parsed = ElicitResultSchema.safeParse(response)
    if (!parsed.success) {
        return { outcome: 'invalid', reason: 'The client returned a malformed elicitation result.' }
    }
    if (parsed.data.action === 'decline') {
        return { outcome: 'declined' }
    }
    if (parsed.data.action === 'cancel') {
        return { outcome: 'cancelled' }
    }
    const choice = parsed.data.content?.choice
    if (typeof choice !== 'string' || !input.options.some((option) => option.id === choice)) {
        return { outcome: 'invalid', reason: 'The answer does not match any requested option.' }
    }
    const note = parsed.data.content?.note
    return typeof note === 'string' && note.trim()
        ? { outcome: 'answered', option_id: choice, note: note.trim().slice(0, NOTE_MAX_LENGTH) }
        : { outcome: 'answered', option_id: choice }
}
