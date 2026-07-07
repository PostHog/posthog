import {
    deriveQuestionOptionId,
    extractSandboxQuestionAnswer,
    parseSandboxQuestionAnswers,
    parseSandboxQuestions,
    type AgentQuestion,
} from './questionUtils'

describe('questionUtils', () => {
    describe('parseSandboxQuestions', () => {
        it('parses the { questions: [...] } shape with options and descriptions', () => {
            const result = parseSandboxQuestions({
                questions: [
                    {
                        question: 'Which goal matters most?',
                        header: 'Goal',
                        multiSelect: false,
                        options: [{ label: 'Activation', description: 'aha moment' }, { label: 'Revenue' }],
                    },
                ],
            })

            expect(result).toEqual([
                {
                    question: 'Which goal matters most?',
                    header: 'Goal',
                    multiSelect: false,
                    options: [{ label: 'Activation', description: 'aha moment' }, { label: 'Revenue' }],
                },
            ])
        })

        it('normalizes a single { question, options } shape into a one-element array', () => {
            const result = parseSandboxQuestions({
                question: 'Pick one',
                options: [{ label: 'A' }, { label: 'B' }],
                multiSelect: true,
            })

            expect(result).toHaveLength(1)
            expect(result[0].question).toEqual('Pick one')
            expect(result[0].multiSelect).toBe(true)
            expect(result[0].options).toEqual([{ label: 'A' }, { label: 'B' }])
        })

        it('drops malformed entries and returns [] when nothing is parseable', () => {
            expect(parseSandboxQuestions({ questions: [{ noQuestion: true }, 'nope'] })).toEqual([])
            expect(parseSandboxQuestions({})).toEqual([])
            expect(parseSandboxQuestions(null)).toEqual([])
        })
    })

    describe('parseSandboxQuestionAnswers', () => {
        it('reads a bare answers map keyed by question text', () => {
            expect(parseSandboxQuestionAnswers({ answers: { 'Which goal?': 'Revenue' } })).toEqual({
                'Which goal?': 'Revenue',
            })
        })

        it('reads an answers map wrapped under output and joins array values', () => {
            expect(parseSandboxQuestionAnswers({ output: { answers: { Products: ['Insights', 'Flags'] } } })).toEqual({
                Products: 'Insights, Flags',
            })
        })

        it('returns {} when there is no answers map', () => {
            expect(parseSandboxQuestionAnswers({ text: 'hi' })).toEqual({})
            expect(parseSandboxQuestionAnswers(undefined)).toEqual({})
        })
    })

    describe('extractSandboxQuestionAnswer', () => {
        const cases: [string, unknown, string | null][] = [
            ['a bare string', 'Revenue', 'Revenue'],
            ['an answer field', { answer: 'Revenue' }, 'Revenue'],
            ['a joined answers map', { answers: { q1: 'A', q2: 'B' } }, 'A, B'],
            ['a text field', { text: 'done' }, 'done'],
            ['a content field', { content: 'picked' }, 'picked'],
            ['nothing usable', { foo: 1 }, null],
        ]

        it.each(cases)('extracts from %s', (_label, result, expected) => {
            expect(extractSandboxQuestionAnswer(result)).toEqual(expected)
        })
    })

    describe('deriveQuestionOptionId', () => {
        const question: AgentQuestion = {
            question: 'Pick',
            multiSelect: false,
            options: [{ label: 'Activation' }, { label: 'Revenue' }],
        }

        it('uses the index of the first selected option', () => {
            expect(deriveQuestionOptionId(question, ['Revenue'])).toEqual('option_1')
        })

        it('falls back to option_0 for a free-typed answer that matches no option', () => {
            expect(deriveQuestionOptionId(question, ['Cut churn'])).toEqual('option_0')
            expect(deriveQuestionOptionId(question, [])).toEqual('option_0')
        })
    })
})
