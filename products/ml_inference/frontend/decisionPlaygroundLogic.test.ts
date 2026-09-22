import { buildDecideRequest, parseCriteria, questionsFromJson, questionsToJson } from './decisionPlaygroundLogic'

describe('decisionPlaygroundLogic request building', () => {
    it.each([
        [
            'billing: payments, invoices\nsupport: product questions',
            { billing: 'payments, invoices', support: 'product questions' },
        ],
        ['  yes  \n\nno', { yes: 'yes', no: 'no' }],
        ['', undefined],
    ])('parses criteria lines %p', (criteria, expected) => {
        expect(parseCriteria(criteria)).toEqual(expected)
    })

    it('sends options for a choice question and a label list for a score question', () => {
        const body = buildDecideRequest('ticket text', [
            { key: 'urgent', type: 'noul', instructions: 'Urgent?', criteria: 'stale: ignored' },
            { key: 'queue', type: 'choice', instructions: 'Which team?', criteria: 'billing: money' },
            { key: 'tone', type: 'score', instructions: 'How upset?', criteria: 'calm\n\nangry ' },
        ])

        expect(body).toEqual({
            state: 'ticket text',
            questions: {
                urgent: { type: 'noul', instructions: 'Urgent?' },
                queue: { type: 'choice', instructions: 'Which team?', criteria: { billing: 'money' } },
                tone: { type: 'score', instructions: 'How upset?', criteria: ['calm', 'angry'] },
            },
        })
    })

    it('round-trips questions through the JSON view', () => {
        const questions = [
            { key: 'urgent', type: 'noul' as const, instructions: 'Urgent?', criteria: '' },
            { key: 'queue', type: 'choice' as const, instructions: 'Which team?', criteria: 'billing: money' },
            { key: 'tone', type: 'score' as const, instructions: 'How upset?', criteria: 'calm\nangry' },
        ]

        expect(questionsFromJson(questionsToJson(questions))).toEqual(questions)
    })

    it.each([
        ['[]', 'must be an object'],
        ['{"urgent": "yes"}', 'must be an object with a type'],
        ['{"urgent": {"type": "maybe", "instructions": "?"}}', 'needs a type'],
        ['{"urgent": {"type": "noul"}}', 'needs instructions'],
        ['{"queue": {"type": "choice", "instructions": "?", "criteria": ["a"]}}', 'criteria must be an object'],
        ['{"tone": {"type": "score", "instructions": "?", "criteria": {"a": "b"}}}', 'criteria must be a list'],
    ])('rejects %s with a message naming the problem', (text, message) => {
        expect(() => questionsFromJson(text)).toThrow(message)
    })
})
