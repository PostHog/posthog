import { buildDecideRequest, questionsFromJson, questionsToJson } from './decisionPlaygroundLogic'

describe('decisionPlaygroundLogic request building', () => {
    it('sends named options for a choice question and a label list for a score question', () => {
        const body = buildDecideRequest('ticket text', [
            {
                key: 'urgent',
                type: 'noul',
                instructions: 'Urgent?',
                options: [{ key: 'o1', name: 'stale', meaning: 'ignored' }],
            },
            {
                key: 'queue',
                type: 'choice',
                instructions: 'Which team?',
                options: [
                    { key: 'o2', name: ' billing ', meaning: 'money' },
                    { key: 'o3', name: 'support', meaning: '' },
                    { key: 'o4', name: '', meaning: 'no name, dropped' },
                ],
            },
            {
                key: 'tone',
                type: 'score',
                instructions: 'How upset?',
                options: [
                    { key: 'o5', name: 'calm', meaning: '' },
                    { key: 'o6', name: '', meaning: '' },
                    { key: 'o7', name: 'angry', meaning: '' },
                ],
            },
        ])

        expect(body).toEqual({
            state: 'ticket text',
            questions: {
                urgent: { type: 'noul', instructions: 'Urgent?' },
                queue: {
                    type: 'choice',
                    instructions: 'Which team?',
                    criteria: { billing: 'money', support: 'support' },
                },
                tone: { type: 'score', instructions: 'How upset?', criteria: ['calm', 'angry'] },
            },
        })
    })

    it('round-trips questions through the JSON view', () => {
        const questions = [
            { key: 'urgent', type: 'noul' as const, instructions: 'Urgent?', options: [] },
            {
                key: 'queue',
                type: 'choice' as const,
                instructions: 'Which team?',
                options: [{ key: 'queue-option-0', name: 'billing', meaning: 'money' }],
            },
            {
                key: 'tone',
                type: 'score' as const,
                instructions: 'How upset?',
                options: [
                    { key: 'tone-option-0', name: 'calm', meaning: '' },
                    { key: 'tone-option-1', name: 'angry', meaning: '' },
                ],
            },
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
        ['{"tone": {"type": "score", "instructions": "?", "criteria": ["calm", null]}}', 'scale label 2 must be text'],
        ['{"queue": {"type": "choice", "instructions": "?", "criteria": {"a": {"b": 1}}}}', 'option "a" must be text'],
    ])('rejects %s with a message naming the problem', (text, message) => {
        expect(() => questionsFromJson(text)).toThrow(message)
    })
})
