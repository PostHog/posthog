import {
    buildSentimentBarTooltip,
    buildTagTooltip,
    capitalize,
    computeExtremes,
    flattenGenerationMessages,
    formatScore,
} from './sentimentUtils'

describe('sentimentUtils', () => {
    describe('capitalize', () => {
        it.each([
            ['positive', 'Positive'],
            ['negative', 'Negative'],
            ['neutral', 'Neutral'],
            ['hello world', 'Hello world'],
        ])('capitalize(%s) → %s', (input, expected) => {
            expect(capitalize(input)).toBe(expected)
        })
    })

    describe('formatScore', () => {
        it.each([
            [0.92, '92%'],
            [0.0, '0%'],
            [1.0, '100%'],
            [0.456, '46%'],
            [0.005, '1%'],
            [undefined, '?'],
        ])('formatScore(%s) → %s', (input, expected) => {
            expect(formatScore(input)).toBe(expected)
        })
    })

    describe('buildTagTooltip', () => {
        it('returns label only when no scores provided', () => {
            expect(buildTagTooltip('positive')).toBe('Sentiment: positive')
        })

        it('returns all three scores when provided', () => {
            expect(buildTagTooltip('positive', { positive: 0.92, neutral: 0.05, negative: 0.03 })).toBe(
                'Positive: 92%\nNeutral: 5%\nNegative: 3%'
            )
        })
    })

    describe('computeExtremes', () => {
        it.each([
            ['no messages', undefined, { maxPositive: 0, maxNegative: 0 }],
            ['empty messages', {}, { maxPositive: 0, maxNegative: 0 }],
            [
                'only positive messages',
                {
                    0: { label: 'positive', scores: { positive: 0.8, neutral: 0.1, negative: 0.1 } },
                    1: { label: 'positive', scores: { positive: 0.95, neutral: 0.03, negative: 0.02 } },
                },
                { maxPositive: 0.95, maxNegative: 0 },
            ],
            [
                'only negative messages',
                {
                    0: { label: 'negative', scores: { positive: 0.05, neutral: 0.1, negative: 0.85 } },
                },
                { maxPositive: 0, maxNegative: 0.85 },
            ],
            [
                'mixed messages',
                {
                    0: { label: 'positive', scores: { positive: 0.9, neutral: 0.05, negative: 0.05 } },
                    1: { label: 'negative', scores: { positive: 0.1, neutral: 0.1, negative: 0.8 } },
                    2: { label: 'neutral', scores: { positive: 0.3, neutral: 0.5, negative: 0.2 } },
                },
                { maxPositive: 0.9, maxNegative: 0.8 },
            ],
            [
                'neutral messages only (no positive/negative labels)',
                {
                    0: { label: 'neutral', scores: { positive: 0.2, neutral: 0.6, negative: 0.2 } },
                },
                { maxPositive: 0, maxNegative: 0 },
            ],
            ['messages without scores', { 0: { label: 'positive' } }, { maxPositive: 0, maxNegative: 0 }],
        ] as const)('%s', (_name, messages, expected) => {
            expect(computeExtremes(messages as any)).toEqual(expected)
        })
    })

    describe('buildSentimentBarTooltip', () => {
        it.each([
            ['label only (no extremes)', 'positive', 80, 0, 0, 'Positive: 80%'],
            ['with max positive only', 'positive', 80, 0.9, 0, 'Positive: 80% (max positive: 90%)'],
            ['with max negative only', 'negative', 75, 0, 0.85, 'Negative: 75% (max negative: 85%)'],
            ['with both extremes', 'positive', 65, 0.95, 0.8, 'Positive: 65% (max positive: 95%, max negative: 80%)'],
            ['extremes below threshold are hidden', 'neutral', 60, 0.03, 0.04, 'Neutral: 60%'],
        ] as const)('%s', (_name, label, widthPercent, maxPos, maxNeg, expected) => {
            expect(buildSentimentBarTooltip(label, widthPercent, maxPos, maxNeg)).toBe(expected)
        })
    })

    describe('flattenGenerationMessages', () => {
        it('returns undefined for undefined input', () => {
            expect(flattenGenerationMessages(undefined)).toBeUndefined()
        })

        it('returns undefined for empty generations', () => {
            expect(flattenGenerationMessages({})).toBeUndefined()
        })

        it('returns undefined when all generations have no messages', () => {
            expect(flattenGenerationMessages({ gen1: {}, gen2: { messages: {} } })).toBeUndefined()
        })

        it('flattens messages from multiple generations', () => {
            const result = flattenGenerationMessages({
                gen1: {
                    messages: {
                        0: { label: 'positive', scores: { positive: 0.9 } },
                        1: { label: 'neutral', scores: { neutral: 0.7 } },
                    },
                },
                gen2: {
                    messages: {
                        0: { label: 'negative', scores: { negative: 0.8 } },
                    },
                },
            })
            expect(result).toEqual({
                'gen1:0': { label: 'positive', scores: { positive: 0.9 } },
                'gen1:1': { label: 'neutral', scores: { neutral: 0.7 } },
                'gen2:0': { label: 'negative', scores: { negative: 0.8 } },
            })
        })

        it('handles single generation', () => {
            const result = flattenGenerationMessages({
                abc: {
                    messages: {
                        0: { label: 'positive' },
                    },
                },
            })
            expect(result).toEqual({ 'abc:0': { label: 'positive' } })
        })
    })
})
