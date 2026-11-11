import { describe, expect, it } from 'vitest'

import { ScoreDefinitionConfigSchema } from '@/schema/tool-inputs'

describe('Scorer passing configuration', () => {
    it.each([
        { options: [{ key: 'good', label: 'Good' }], passing_rule: { categories: ['good'] } },
        {},
        { true_is_failure: null },
        { true_is_failure: false },
        { true_is_failure: true, true_label: 'Defect', false_label: 'Clear' },
        { passing_rule: null },
        { min: 0, max: 5, passing_rule: { operator: 'gte', threshold: 3 } },
        { passing_rule: { operator: 'lte', threshold: 0.5 } },
    ])('preserves explicit rules and omitted polarity: %j', (config) => {
        expect(ScoreDefinitionConfigSchema.parse(config)).toEqual(config)
    })

    it.each([
        { passing_rule: { operator: 'gt', threshold: 3 } },
        { passing_rule: { operator: 'gte' } },
        { passing_rule: { operator: 'gte', threshold: true } },
        { passing_rule: { operator: 'gte', threshold: Infinity } },
        { passing_rule: { operator: 'gte', threshold: 3, unexpected: true } },
        { true_is_failure: false, passing_rule: { operator: 'gte', threshold: 3 } },
    ])('rejects malformed or mixed scorer configuration: %j', (config) => {
        expect(ScoreDefinitionConfigSchema.safeParse(config).success).toBe(false)
    })
})
