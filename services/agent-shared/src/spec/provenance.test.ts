import { describe, expect, it } from 'vitest'

import { EXTERNAL_CONTENT_NATIVE_TOOL_IDS, nativeToolResultProvenance } from './provenance'

describe('nativeToolResultProvenance', () => {
    it('marks external-content readers as external', () => {
        for (const id of [
            '@posthog/web-search',
            '@posthog/web-fetch',
            '@posthog/http-request',
            '@posthog/slack-read-channel',
            '@posthog/slack-read-thread',
            '@posthog/query',
        ]) {
            expect(nativeToolResultProvenance(id)).toBe('external')
            expect(EXTERNAL_CONTENT_NATIVE_TOOL_IDS.has(id)).toBe(true)
        }
    })

    it('defaults first-party tools to internal', () => {
        for (const id of [
            '@posthog/memory-write',
            '@posthog/table-append',
            '@posthog/slack-post-message',
            '@posthog/meta-end-turn',
            '@posthog/unknown-future-tool',
        ]) {
            expect(nativeToolResultProvenance(id)).toBe('internal')
        }
    })
})
