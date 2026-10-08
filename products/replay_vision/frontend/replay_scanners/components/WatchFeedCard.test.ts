import type { ReplayObservationApi, WatchFeedReasonApi } from '../../generated/api.schemas'
import {
    watchFeedRowSentence,
    watchFeedRowTitle,
    observationKeyMomentMs,
    watchCardHeadline,
    watchStartSeconds,
} from './WatchFeedCard'

describe('WatchFeedCard helpers', () => {
    const observation = (scannerType: string | undefined, output: Record<string, unknown>): ReplayObservationApi =>
        ({
            scanner_snapshot: scannerType ? { scanner_type: scannerType } : undefined,
            scanner_result: { model_output: output },
        }) as unknown as ReplayObservationApi

    describe('observationKeyMomentMs', () => {
        it.each<{ name: string; output: Record<string, unknown>; expected: number | null }>([
            { name: 'reads the key moment', output: { key_moment_ms: 42_000 }, expected: 42_000 },
            { name: 'keeps a key moment at the very start', output: { key_moment_ms: 0 }, expected: 0 },
            { name: 'is null on a scan from before key moments', output: {}, expected: null },
            { name: 'is null when the scan skipped the pick', output: { key_moment_ms: null }, expected: null },
            { name: 'ignores a value that is not a number', output: { key_moment_ms: '42' }, expected: null },
        ])('$name', ({ output, expected }) => {
            expect(observationKeyMomentMs(observation('monitor', output))).toBe(expected)
        })
    })

    describe('watchStartSeconds', () => {
        it.each<{ name: string; keyMomentMs: number | null; expected: number }>([
            { name: 'starts from the beginning without a key moment', keyMomentMs: null, expected: 0 },
            { name: 'starts a few seconds before the key moment', keyMomentMs: 42_900, expected: 39 },
            { name: 'never starts before the recording', keyMomentMs: 1_000, expected: 0 },
        ])('$name', ({ keyMomentMs, expected }) => {
            expect(watchStartSeconds(keyMomentMs)).toBe(expected)
        })
    })

    describe('watchFeedRowSentence', () => {
        it("prefers the scan's notability sentence over the derived headline", () => {
            const sentence = watchFeedRowSentence(
                observation('monitor', { reasoning: 'Retried the form twice. The submit then failed.' }),
                {
                    kind: 'jev_watchable',
                    jev_probability: 0.9,
                    notability_reason: 'The card form rejected a valid card three times.',
                } as WatchFeedReasonApi
            )
            expect(sentence).toBe('The card form rejected a valid card three times.')
        })

        it('derives the headline when the reason carries no notability sentence', () => {
            const sentence = watchFeedRowSentence(
                observation('monitor', { reasoning: 'Retried the form twice. The submit then failed.' }),
                { kind: 'jev_watchable', jev_probability: 0.9 } as WatchFeedReasonApi
            )
            expect(sentence).toBe('Retried the form twice.')
        })

        it('falls back to the scanner name when the scan wrote no prose', () => {
            const bare = {
                scanner_snapshot: { name: 'Confused checkout', scanner_type: 'monitor' },
                scanner_result: { model_output: {} },
            } as unknown as ReplayObservationApi
            expect(watchFeedRowSentence(bare, { kind: 'unviewed_recent' } as WatchFeedReasonApi)).toBe(
                'Confused checkout'
            )
        })
    })

    describe('watchFeedRowTitle', () => {
        const notable = {
            kind: 'jev_watchable',
            jev_probability: 0.9,
            notability_reason: 'The card form rejected a valid card three times.',
        } as WatchFeedReasonApi
        it.each<{ name: string; scannerType: string; output: Record<string, unknown>; expected: string }>([
            {
                name: "leads with a summarizer's authored title over the scan's sentence",
                scannerType: 'summarizer',
                output: { title: 'Checkout card rejected', summary: 'Tried the card three times. Left.' },
                expected: 'Checkout card rejected',
            },
            {
                name: 'falls back to the card sentence for an untitled summarizer',
                scannerType: 'summarizer',
                output: { title: '', summary: 'Tried the card three times. Left.' },
                expected: 'The card form rejected a valid card three times.',
            },
            {
                name: 'leads other scan types with the card sentence',
                scannerType: 'monitor',
                output: { reasoning: 'Retried the form twice. The submit then failed.' },
                expected: 'The card form rejected a valid card three times.',
            },
        ])('$name', ({ scannerType, output, expected }) => {
            expect(watchFeedRowTitle(observation(scannerType, output), notable)).toBe(expected)
        })
    })

    describe('watchCardHeadline', () => {
        it.each<{
            name: string
            scannerType: string
            output: Record<string, unknown>
            expected: ReturnType<typeof watchCardHeadline>
        }>([
            {
                name: 'keeps the authored summarizer title and rides the summary along as the body',
                scannerType: 'summarizer',
                output: { title: 'Quick bug report', summary: 'Filed feedback (t 30) from the toast.' },
                expected: {
                    title: 'Quick bug report',
                    body: { text: 'Filed feedback (t 30) from the toast.', segments: undefined },
                },
            },
            {
                name: 'derives the headline from the summary when the summarizer title is empty',
                scannerType: 'summarizer',
                output: { title: '', summary: 'Applied a coupon (t 12). Abandoned the cart.' },
                expected: { title: 'Applied a coupon (00:12).', body: { text: 'Abandoned the cart.' } },
            },
            {
                name: 'promotes the first reasoning sentence, rest becomes the body',
                scannerType: 'monitor',
                output: { reasoning: 'Retried the form twice. The submit then failed.' },
                expected: { title: 'Retried the form twice.', body: { text: 'The submit then failed.' } },
            },
            {
                name: 'leaves the body empty when the reasoning is a single sentence',
                scannerType: 'monitor',
                output: { reasoning: 'Retried the form twice.' },
                expected: { title: 'Retried the form twice.', body: null },
            },
            {
                name: 'never splits the headline inside a decimal',
                scannerType: 'scorer',
                output: { reasoning: 'Scored 9.5 on intent. Opened billing after.' },
                expected: { title: 'Scored 9.5 on intent.', body: { text: 'Opened billing after.' } },
            },
            {
                name: 'keeps a mid-sentence citation as a plain timestamp',
                scannerType: 'monitor',
                output: { reasoning: 'Compares plans at (t 30), then upgrades. Leaves happy.' },
                expected: { title: 'Compares plans at (00:30), then upgrades.', body: { text: 'Leaves happy.' } },
            },
            {
                name: 'never splits the headline at an abbreviation',
                scannerType: 'monitor',
                output: { reasoning: 'Hit errors, e.g. a 500 vs. the usual 200. They retried.' },
                expected: { title: 'Hit errors, e.g. a 500 vs. the usual 200.', body: { text: 'They retried.' } },
            },
            {
                name: 'keeps the space before a dot-prefixed word',
                scannerType: 'monitor',
                output: { reasoning: 'Opened the .env editor. Saved it.' },
                expected: { title: 'Opened the .env editor.', body: { text: 'Saved it.' } },
            },
        ])('$name', ({ scannerType, output, expected }) => {
            expect(watchCardHeadline(observation(scannerType, output))).toEqual(expected)
        })
    })
})
