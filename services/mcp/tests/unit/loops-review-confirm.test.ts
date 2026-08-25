import { describe, expect, it } from 'vitest'

import { buildReviewedConfig, extractConfirmationHash } from '@/ui-apps/apps/loops-review-confirm'
import { APP_DATA_META_KEY } from '@/ui-apps/types'

import type { LoopReviewData } from 'products/tasks/mcp/apps'

describe('loops-review confirm helpers', () => {
    describe('buildReviewedConfig', () => {
        it('forwards reviewed fields and drops anything else', () => {
            const data = {
                name: 'Open PR summary',
                instructions: 'Summarize open PRs',
                visibility: 'team',
                overlap_policy: 'allow',
                _posthogUrl: 'https://us.posthog.com',
                injected_field: 'must never travel',
            } as unknown as LoopReviewData

            const config = buildReviewedConfig(data)

            expect(config).toMatchObject({
                name: 'Open PR summary',
                instructions: 'Summarize open PRs',
                visibility: 'team',
                overlap_policy: 'allow',
            })
            expect(config).not.toHaveProperty('_posthogUrl')
            expect(config).not.toHaveProperty('injected_field')
        })
    })

    describe('extractConfirmationHash', () => {
        it.each<[string, { _meta?: Record<string, unknown>; structuredContent?: unknown }, string | undefined]>([
            [
                'reads the hash from the _meta app channel',
                { _meta: { [APP_DATA_META_KEY]: { confirmation_hash: 'hash-from-meta' } } },
                'hash-from-meta',
            ],
            [
                'prefers _meta over structuredContent',
                {
                    _meta: { [APP_DATA_META_KEY]: { confirmation_hash: 'hash-from-meta' } },
                    structuredContent: { confirmation_hash: 'hash-from-structured' },
                },
                'hash-from-meta',
            ],
            [
                'falls back to structuredContent',
                { structuredContent: { confirmation_hash: 'hash-from-structured' } },
                'hash-from-structured',
            ],
            ['returns undefined when neither channel has a hash', { _meta: {} }, undefined],
            ['returns undefined for a non-string hash', { structuredContent: { confirmation_hash: 42 } }, undefined],
        ])('%s', (_label, prepared, expected) => {
            expect(extractConfirmationHash(prepared)).toBe(expected)
        })
    })
})
