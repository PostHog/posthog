import { describe, expect, it } from 'vitest'

import { FilterGroupsSchema, MultivariateSchema } from '@/schema/flags'

describe('MultivariateSchema', () => {
    describe('duplicate variant key validation', () => {
        it('should reject duplicate variant keys', () => {
            const input = {
                variants: [
                    { key: 'control', rollout_percentage: 50 },
                    { key: 'control', rollout_percentage: 50 },
                ],
            }

            const result = MultivariateSchema.safeParse(input)
            expect(result.success).toBe(false)
            if (!result.success) {
                expect(result.error.issues.some((i) => i.message.includes('Duplicate variant keys'))).toBe(true)
            }
        })

        it('should accept unique variant keys', () => {
            const input = {
                variants: [
                    { key: 'control', rollout_percentage: 50 },
                    { key: 'test', rollout_percentage: 50 },
                ],
            }

            const result = MultivariateSchema.safeParse(input)
            expect(result.success).toBe(true)
        })
    })
})

describe('FilterGroupsSchema', () => {
    describe('variant cross-validation', () => {
        it('should reject group variant that does not exist in multivariate.variants', () => {
            const input = {
                groups: [{ variant: 'nonexistent', properties: [], rollout_percentage: 100 }],
                multivariate: {
                    variants: [
                        { key: 'control', rollout_percentage: 50 },
                        { key: 'test', rollout_percentage: 50 },
                    ],
                },
            }

            const result = FilterGroupsSchema.safeParse(input)
            expect(result.success).toBe(false)
            if (!result.success) {
                expect(result.error.issues[0]!.message).toContain("references variant 'nonexistent'")
            }
        })

        it('should accept group variant that exists in multivariate.variants', () => {
            const input = {
                groups: [{ variant: 'test', properties: [], rollout_percentage: 100 }],
                multivariate: {
                    variants: [
                        { key: 'control', rollout_percentage: 50 },
                        { key: 'test', rollout_percentage: 50 },
                    ],
                },
            }

            const result = FilterGroupsSchema.safeParse(input)
            expect(result.success).toBe(true)
        })

        it('should accept null variant', () => {
            const input = {
                groups: [{ variant: null, properties: [], rollout_percentage: 100 }],
                multivariate: {
                    variants: [
                        { key: 'control', rollout_percentage: 50 },
                        { key: 'test', rollout_percentage: 50 },
                    ],
                },
            }

            const result = FilterGroupsSchema.safeParse(input)
            expect(result.success).toBe(true)
        })

        it('should accept groups without variant when multivariate is present', () => {
            const input = {
                groups: [{ properties: [], rollout_percentage: 100 }],
                multivariate: {
                    variants: [
                        { key: 'control', rollout_percentage: 50 },
                        { key: 'test', rollout_percentage: 50 },
                    ],
                },
            }

            const result = FilterGroupsSchema.safeParse(input)
            expect(result.success).toBe(true)
        })

        it('should not validate variant when multivariate is not present', () => {
            const input = {
                groups: [{ variant: 'any-value', properties: [], rollout_percentage: 100 }],
            }

            const result = FilterGroupsSchema.safeParse(input)
            expect(result.success).toBe(true)
        })
    })
})
