import { describe, expect, it } from 'vitest'

import {
    buildDecisionElicitation,
    DecisionRequestInputSchema,
    parseDecisionResponse,
} from '@/tools/decisionRequest/contract'

const request = DecisionRequestInputSchema.parse({
    question: 'Roll the flag out to 100%?',
    options: [
        { id: 'ship', label: 'Ship it', description: 'Set rollout to 100%' },
        { id: 'hold', label: 'Hold' },
    ],
    context: 'Error rate is flat at 50%.',
})

describe('decision request contract', () => {
    it('builds a form with the context in the message and one choice per option', () => {
        expect(buildDecisionElicitation(request)).toEqual({
            mode: 'form',
            message: 'Roll the flag out to 100%?\n\nError rate is flat at 50%.',
            requestedSchema: {
                type: 'object',
                properties: {
                    choice: {
                        type: 'string',
                        title: 'Decision',
                        oneOf: [
                            { const: 'ship', title: 'Ship it: Set rollout to 100%' },
                            { const: 'hold', title: 'Hold' },
                        ],
                    },
                    note: { type: 'string', title: 'Note for the agent (optional)', maxLength: 1000 },
                },
                required: ['choice'],
            },
        })
    })

    const option = (id: string): { id: string; label: string } => ({ id, label: id })

    it.each([
        ['2 options', [option('a'), option('b')], true],
        ['6 options', ['a', 'b', 'c', 'd', 'e', 'f'].map(option), true],
        ['1 option', [option('a')], false],
        ['7 options', ['a', 'b', 'c', 'd', 'e', 'f', 'g'].map(option), false],
        ['an uppercase option id', [option('Ship'), option('hold')], false],
        ['duplicate option ids', [option('a'), option('a')], false],
    ])('validates a request with %s', (_name, options, valid) => {
        expect(DecisionRequestInputSchema.safeParse({ question: 'Which?', options }).success).toBe(valid)
    })

    it.each([
        [
            'an accepted option',
            { action: 'accept', content: { choice: 'hold' } },
            { outcome: 'answered', option_id: 'hold' },
        ],
        [
            'an accepted option with a note',
            { action: 'accept', content: { choice: 'ship', note: '  go  ' } },
            { outcome: 'answered', option_id: 'ship', note: 'go' },
        ],
        [
            'an accepted option with a blank note',
            { action: 'accept', content: { choice: 'ship', note: '   ' } },
            { outcome: 'answered', option_id: 'ship' },
        ],
        ['a decline', { action: 'decline' }, { outcome: 'declined' }],
        ['a decline with null content', { action: 'decline', content: null }, { outcome: 'declined' }],
        ['a dismissal', { action: 'cancel' }, { outcome: 'cancelled' }],
        ['a dismissal with null content', { action: 'cancel', content: null }, { outcome: 'cancelled' }],
        [
            'a choice that was never offered',
            { action: 'accept', content: { choice: 'delete-everything' } },
            { outcome: 'invalid', reason: 'The answer does not match any requested option.' },
        ],
        [
            'an accept with no choice',
            { action: 'accept', content: {} },
            { outcome: 'invalid', reason: 'The answer does not match any requested option.' },
        ],
        [
            'a malformed result',
            { action: 'approve' },
            { outcome: 'invalid', reason: 'The client returned a malformed elicitation result.' },
        ],
    ])('maps %s to its outcome', (_name, response, expected) => {
        expect(parseDecisionResponse(request, response)).toEqual(expected)
    })
})
