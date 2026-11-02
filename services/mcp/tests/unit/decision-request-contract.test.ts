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
    it('renders each option as a selectable choice the client can validate', () => {
        expect(buildDecisionElicitation(request).requestedSchema.properties.choice.oneOf).toEqual([
            { const: 'ship', title: 'Ship it: Set rollout to 100%' },
            { const: 'hold', title: 'Hold' },
        ])
    })

    it('rejects duplicate option ids', () => {
        expect(
            DecisionRequestInputSchema.safeParse({
                question: 'Which?',
                options: [
                    { id: 'a', label: 'A' },
                    { id: 'a', label: 'Also A' },
                ],
            }).success
        ).toBe(false)
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
        ['a decline', { action: 'decline' }, { outcome: 'declined' }],
        ['a dismissal', { action: 'cancel' }, { outcome: 'cancelled' }],
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
