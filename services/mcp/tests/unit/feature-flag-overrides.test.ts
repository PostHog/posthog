import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import { resolveFeatureFlagOverrides } from '@/lib/posthog/flags'

describe('resolveFeatureFlagOverrides', () => {
    const ORIG_OVERRIDES = process.env.FEATURE_FLAG_OVERRIDES
    const ORIG_NODE_ENV = process.env.NODE_ENV

    beforeEach(() => {
        delete process.env.FEATURE_FLAG_OVERRIDES
        process.env.NODE_ENV = 'test'
    })

    afterEach(() => {
        if (ORIG_OVERRIDES === undefined) {
            delete process.env.FEATURE_FLAG_OVERRIDES
        } else {
            process.env.FEATURE_FLAG_OVERRIDES = ORIG_OVERRIDES
        }
        process.env.NODE_ENV = ORIG_NODE_ENV
    })

    it('parses the env JSON object with boolean and variant values', () => {
        process.env.FEATURE_FLAG_OVERRIDES = JSON.stringify({ 'mcp-sql-schema-discovery': true, 'some-flag': 'variant-a' })
        expect(resolveFeatureFlagOverrides()).toEqual({ 'mcp-sql-schema-discovery': true, 'some-flag': 'variant-a' })
    })

    it('lets a per-request override win over the env var', () => {
        process.env.FEATURE_FLAG_OVERRIDES = JSON.stringify({ 'mcp-sql-schema-discovery': false })
        expect(resolveFeatureFlagOverrides(JSON.stringify({ 'mcp-sql-schema-discovery': true }))).toEqual({
            'mcp-sql-schema-discovery': true,
        })
    })

    it('ignores non-boolean/string values, arrays, and malformed JSON', () => {
        process.env.FEATURE_FLAG_OVERRIDES = JSON.stringify({ a: 1, b: true, c: null, d: { nested: 1 } })
        expect(resolveFeatureFlagOverrides('not-json')).toEqual({ b: true })
        expect(resolveFeatureFlagOverrides('[1,2,3]')).toEqual({ b: true })
    })

    it('is a no-op in production, even with overrides set', () => {
        process.env.NODE_ENV = 'production'
        process.env.FEATURE_FLAG_OVERRIDES = JSON.stringify({ 'mcp-sql-schema-discovery': true })
        expect(resolveFeatureFlagOverrides(JSON.stringify({ x: true }))).toEqual({})
    })

    it('fails closed when NODE_ENV is unset, even with overrides set', () => {
        delete process.env.NODE_ENV
        process.env.FEATURE_FLAG_OVERRIDES = JSON.stringify({ 'mcp-sql-schema-discovery': true })
        expect(resolveFeatureFlagOverrides(JSON.stringify({ x: true }))).toEqual({})
    })

    it('returns an empty object when nothing is set', () => {
        expect(resolveFeatureFlagOverrides()).toEqual({})
    })
})
