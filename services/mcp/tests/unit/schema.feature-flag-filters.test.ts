import { describe, expect, it } from 'vitest'

import { FeatureFlagsCreateBody, FeatureFlagsListQueryParams } from '@/generated/feature_flags/api'
import { CreateSurveyInputSchema } from '@/schema/surveys'

describe('Feature flag filter schemas', () => {
    it('should accept valid feature flag filters from OpenAPI schema', () => {
        const result = FeatureFlagsCreateBody.shape.filters.safeParse({
            groups: [
                {
                    properties: [
                        {
                            key: 'email',
                            type: 'person',
                            value: '@company.com',
                            operator: 'icontains',
                        },
                    ],
                    rollout_percentage: 100,
                },
            ],
        })

        expect(result.success).toBe(true)
    })

    it('should reject invalid feature flag filters from OpenAPI schema', () => {
        const result = FeatureFlagsCreateBody.shape.filters.safeParse('not-an-object')

        expect(result.success).toBe(false)
    })

    it("should reject non-'flag_evaluates_to' operators for flag property filters", () => {
        const result = FeatureFlagsCreateBody.shape.filters.safeParse({
            groups: [
                {
                    properties: [
                        {
                            key: '123',
                            type: 'flag',
                            operator: 'exact',
                            value: true,
                        },
                    ],
                },
            ],
        })

        expect(result.success).toBe(false)
    })

    it('should reject non-string values for semver operators', () => {
        const result = FeatureFlagsCreateBody.shape.filters.safeParse({
            groups: [
                {
                    properties: [
                        {
                            key: 'app_version',
                            type: 'person',
                            operator: 'semver_gt',
                            value: 123,
                        },
                    ],
                },
            ],
        })

        expect(result.success).toBe(false)
    })

    it('should reject non-array values for icontains_multi operators', () => {
        const result = FeatureFlagsCreateBody.shape.filters.safeParse({
            groups: [
                {
                    properties: [
                        {
                            key: 'email',
                            type: 'person',
                            operator: 'icontains_multi',
                            value: '@company.com',
                        },
                    ],
                },
            ],
        })

        expect(result.success).toBe(false)
    })

    it('should use feature flag filters schema for survey targeting filters', () => {
        const result = CreateSurveyInputSchema.safeParse({
            name: 'Survey with targeting filters',
            questions: [{ type: 'open', question: 'How was your experience?' }],
            targeting_flag_filters: {
                groups: [
                    {
                        properties: [
                            {
                                key: 'email',
                                type: 'person',
                                value: '@company.com',
                                operator: 'icontains',
                            },
                        ],
                        rollout_percentage: 100,
                    },
                ],
            },
        })

        expect(result.success).toBe(true)
    })

    it('should keep feature flag list search/filter query params valid', () => {
        const result = FeatureFlagsListQueryParams.safeParse({
            search: 'checkout-flag',
            type: 'remote_config',
            limit: 10,
            offset: 0,
        })

        expect(result.success).toBe(true)
    })
})

describe('Multivariate schema', () => {
    const filtersSchema = FeatureFlagsCreateBody.shape.filters

    it('should accept valid multivariate variants', () => {
        const result = filtersSchema.safeParse({
            groups: [{ properties: [], rollout_percentage: 100 }],
            multivariate: {
                variants: [
                    { key: 'control', rollout_percentage: 50 },
                    { key: 'test', rollout_percentage: 50 },
                ],
            },
        })

        expect(result.success).toBe(true)
    })

    it('should require key on each variant', () => {
        const result = filtersSchema.safeParse({
            groups: [{ properties: [], rollout_percentage: 100 }],
            multivariate: {
                variants: [{ rollout_percentage: 50 }],
            },
        })

        expect(result.success).toBe(false)
    })

    it('should require rollout_percentage on each variant', () => {
        const result = filtersSchema.safeParse({
            groups: [{ properties: [], rollout_percentage: 100 }],
            multivariate: {
                variants: [{ key: 'control' }],
            },
        })

        expect(result.success).toBe(false)
    })

    it('should accept optional variant name', () => {
        const result = filtersSchema.safeParse({
            multivariate: {
                variants: [{ key: 'control', name: 'Control Group', rollout_percentage: 100 }],
            },
        })

        expect(result.success).toBe(true)
        if (result.success) {
            expect(result.data?.multivariate?.variants[0]?.name).toBe('Control Group')
        }
    })

    it('should accept filters without multivariate (boolean flags)', () => {
        const result = filtersSchema.safeParse({
            groups: [{ properties: [], rollout_percentage: 100 }],
        })

        expect(result.success).toBe(true)
    })
})

describe('Filter groups schema', () => {
    const filtersSchema = FeatureFlagsCreateBody.shape.filters

    it('should accept groups with variant override', () => {
        const result = filtersSchema.safeParse({
            groups: [{ variant: 'test', properties: [], rollout_percentage: 100 }],
            multivariate: {
                variants: [
                    { key: 'control', rollout_percentage: 50 },
                    { key: 'test', rollout_percentage: 50 },
                ],
            },
        })

        expect(result.success).toBe(true)
        if (result.success) {
            expect(result.data?.groups?.[0]?.variant).toBe('test')
        }
    })

    it('should accept null variant on groups', () => {
        const result = filtersSchema.safeParse({
            groups: [{ variant: null, properties: [], rollout_percentage: 100 }],
            multivariate: {
                variants: [
                    { key: 'control', rollout_percentage: 50 },
                    { key: 'test', rollout_percentage: 50 },
                ],
            },
        })

        expect(result.success).toBe(true)
    })

    it('should accept groups without variant when multivariate is present', () => {
        const result = filtersSchema.safeParse({
            groups: [{ properties: [], rollout_percentage: 100 }],
            multivariate: {
                variants: [
                    { key: 'control', rollout_percentage: 50 },
                    { key: 'test', rollout_percentage: 50 },
                ],
            },
        })

        expect(result.success).toBe(true)
    })

    it('should reject non-numeric rollout_percentage on groups', () => {
        const result = filtersSchema.safeParse({
            groups: [{ properties: [], rollout_percentage: 'fifty' }],
        })

        expect(result.success).toBe(false)
    })

    it('should accept groups with person property filters', () => {
        const result = filtersSchema.safeParse({
            groups: [
                {
                    properties: [
                        { key: 'country', type: 'person', value: 'US', operator: 'exact' },
                        { key: 'age', type: 'person', value: '18', operator: 'gt' },
                    ],
                    rollout_percentage: 50,
                },
            ],
        })

        expect(result.success).toBe(true)
    })
})
