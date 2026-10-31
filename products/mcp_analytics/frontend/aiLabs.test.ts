import { labSqlExpression, modelLab, topModels } from './aiLabs'

describe('aiLabs', () => {
    test.each([
        ['claude-opus-4-5', 'Anthropic'],
        ['gpt-5-codex', 'OpenAI'],
        ['openrouter/o3-mini', 'OpenAI'],
        ['gpt-oss-120b', 'Open weights'],
        ['gemini-2.5-pro', 'Google'],
        ['grok-4', 'xAI'],
        ['composer-1', 'Cursor'],
        ['some-new-model', 'Other'],
    ])('modelLab(%s) is %s', (model, lab) => {
        expect(modelLab(model)).toEqual(lab)
    })

    it('builds the SQL from the same patterns that modelLab matches', () => {
        const sql = labSqlExpression('m')
        expect(sql).toContain("match(lower(m), 'claude|opus|sonnet|haiku|fable|anthropic'), 'Anthropic'")
        expect(sql.startsWith("multiIf(m = 'Unknown', 'Unknown', ")).toBe(true)
        expect(sql.endsWith(", 'Other')")).toBe(true)
    })

    it('uses model names to break ties between top models', () => {
        expect([
            ...topModels([
                ['model-b', 1],
                ['model-a', 1],
            ]),
        ]).toEqual(['model-a', 'model-b'])
    })
})
