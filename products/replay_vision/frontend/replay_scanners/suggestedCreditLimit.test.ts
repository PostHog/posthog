import { type SuggestedCreditLimitInput, suggestedCreditLimit } from './suggestedCreditLimit'

const scanner = (overrides: Partial<SuggestedCreditLimitInput>): SuggestedCreditLimitInput => ({
    credit_limit: null,
    credits_this_month: 0,
    credits_used_against_limit: 0,
    limit_from_free_credits: false,
    credits_per_observation: 20,
    ...overrides,
})

describe('suggestedCreditLimit', () => {
    it.each<[string, Partial<SuggestedCreditLimitInput>, number]>([
        ['a scanner with no limit and no spend', {}, 500],
        ['a scanner at its own limit', { credit_limit: 800, credits_used_against_limit: 800 }, 1200],
        [
            'a free-only scanner that spent the free credits, from its own spend',
            { limit_from_free_credits: true, credits_this_month: 1800, credits_used_against_limit: 2500 },
            2700,
        ],
        [
            'a limit already below the spend',
            { credit_limit: 500, credits_this_month: 1800, credits_used_against_limit: 1800 },
            2700,
        ],
        [
            'an observation that costs more than the raise',
            { credit_limit: 100, credits_used_against_limit: 100, credits_per_observation: 120 },
            300,
        ],
    ])('suggests a limit for %s', (_name, overrides, expected) => {
        const suggested = suggestedCreditLimit(scanner(overrides))
        expect(suggested).toBe(expected)
    })
})
