import { describe, expect, it } from 'vitest'

import { parseToolResultContent, resolveWaitPhase } from '@/ui-apps/hooks/useToolResult'
import { APP_DATA_META_KEY } from '@/ui-apps/types'

describe('useToolResult', () => {
    // `buildToolResultPayload` drops top-level `structuredContent` whenever a compact
    // formatted table takes its place for the model, so for that whole class of tools the
    // `_meta` channel is the only copy of the data the app can draw.
    describe('parseToolResultContent', () => {
        it.each([
            ['structuredContent when the host forwards it', { results: [1] }, undefined, { results: [1] }],
            [
                'the _meta channel when structuredContent is suppressed',
                undefined,
                { [APP_DATA_META_KEY]: { results: [2] } },
                { results: [2] },
            ],
            [
                'structuredContent in preference to the _meta channel',
                { results: [1] },
                { [APP_DATA_META_KEY]: { results: [2] } },
                { results: [1] },
            ],
            ['nothing when neither channel carries data', undefined, { ui: { resourceUri: 'ui://x' } }, null],
            ['nothing when the host forwards no _meta at all', undefined, undefined, null],
        ])('reads %s', (_name, structuredContent, meta, expected) => {
            expect(parseToolResultContent(structuredContent, meta)).toEqual(expected)
        })
    })

    // The watchdog turns an undelivered notification into a retryable error. It must stay
    // off in every state the app can already draw, or a working render gets a timeout
    // error stacked on top of it.
    describe('resolveWaitPhase', () => {
        const waiting = { isConnected: false, hasData: false, isCancelled: false, hasError: false }

        it.each([
            ['before the host connects', waiting, 'connecting'],
            ['after connecting, before a result arrives', { ...waiting, isConnected: true }, 'awaiting-result'],
            ['once a result renders', { ...waiting, isConnected: true, hasData: true }, 'settled'],
            ['once the tool call is cancelled', { ...waiting, isConnected: true, isCancelled: true }, 'settled'],
            ['once the app has an error to show', { ...waiting, hasError: true }, 'settled'],
        ])('is %s', (_name, input, expected) => {
            expect(resolveWaitPhase(input)).toBe(expected)
        })
    })
})
