import { type ElicitRequestFormParams, ElicitResultSchema } from '@modelcontextprotocol/sdk/types.js'
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
        .describe('The choices. The agent must handle every option, plus a decline or dismissal.'),
    context: z
        .string()
        .trim()
        .max(2000)
        .optional()
        .describe('Evidence the human needs to decide: what was found, what is at stake.'),
})

export type DecisionRequestInput = z.infer<typeof DecisionRequestInputSchema>

export type DecisionOutcome =
    | { outcome: 'answered'; option_id: string; note?: string }
    | { outcome: 'declined' }
    | { outcome: 'cancelled' }
    | { outcome: 'invalid'; reason: string }

export function buildDecisionElicitation(input: DecisionRequestInput): ElicitRequestFormParams {
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
