import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import { MCP_OUTPUT_FORMAT_FLAG } from '@/lib/constants'
import { resolveDefaultOutputFormat, resolveFeatureFlagOverrides } from '@/lib/posthog/flags'

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
        process.env.FEATURE_FLAG_OVERRIDES = JSON.stringify({ 'dev-forced-flag': true, 'some-flag': 'variant-a' })
        expect(resolveFeatureFlagOverrides()).toEqual({ 'dev-forced-flag': true, 'some-flag': 'variant-a' })
    })

    it('lets a per-request override win over the env var', () => {
        process.env.FEATURE_FLAG_OVERRIDES = JSON.stringify({ 'dev-forced-flag': false })
        expect(resolveFeatureFlagOverrides(JSON.stringify({ 'dev-forced-flag': true }))).toEqual({
            'dev-forced-flag': true,
        })
    })

    it('ignores non-boolean/string values, arrays, and malformed JSON', () => {
        process.env.FEATURE_FLAG_OVERRIDES = JSON.stringify({ a: 1, b: true, c: null, d: { nested: 1 } })
        expect(resolveFeatureFlagOverrides('not-json')).toEqual({ b: true })
        expect(resolveFeatureFlagOverrides('[1,2,3]')).toEqual({ b: true })
    })

    it('is a no-op in production, even with overrides set', () => {
        process.env.NODE_ENV = 'production'
        process.env.FEATURE_FLAG_OVERRIDES = JSON.stringify({ 'dev-forced-flag': true })
        expect(resolveFeatureFlagOverrides(JSON.stringify({ x: true }))).toEqual({})
    })

    it('fails closed when NODE_ENV is unset, even with overrides set', () => {
        delete process.env.NODE_ENV
        process.env.FEATURE_FLAG_OVERRIDES = JSON.stringify({ 'dev-forced-flag': true })
        expect(resolveFeatureFlagOverrides(JSON.stringify({ x: true }))).toEqual({})
    })

    it('returns an empty object when nothing is set', () => {
        expect(resolveFeatureFlagOverrides()).toEqual({})
    })
})

describe('resolveDefaultOutputFormat', () => {
    // Only the explicit 'json' variant may switch the default: inverting the
    // fail-safe would flip every tool result to JSON whenever flag evaluation
    // fails or local dev's enable-all returns booleans.
    it.each([
        ['json', 'json'],
        ['toon', 'toon'],
        [true, 'toon'],
        [false, 'toon'],
    ] as const)('resolves flag value %j to %s', (flagValue, expected) => {
        expect(resolveDefaultOutputFormat({ [MCP_OUTPUT_FORMAT_FLAG]: flagValue })).toBe(expected)
    })

    it('falls back to toon when flags are missing or the key is unset', () => {
        expect(resolveDefaultOutputFormat(undefined)).toBe('toon')
        expect(resolveDefaultOutputFormat({})).toBe('toon')
    })
})
