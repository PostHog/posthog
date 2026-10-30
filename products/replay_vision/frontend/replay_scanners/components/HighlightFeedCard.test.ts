import type { ReplayObservationApi, HighlightFeedReasonApi } from '../../generated/api.schemas'
import {
    highlightFeedRowSentence,
    highlightFeedRowTitle,
    observationKeyMomentMs,
    highlightCardHeadline,
    highlightReasonCopy,
    highlightStartSeconds,
} from './HighlightFeedCard'

describe('HighlightFeedCard helpers', () => {
    describe('highlightReasonCopy', () => {
        it.each<{ name: string; reason: HighlightFeedReasonApi; expected: string }>([
            {
                name: 'names the category of an embedding pick with no similar sessions',
                reason: {
                    kind: 'embedding_pick',
                    watch_category: 'failure',
                    similar_count: 0,
                } as HighlightFeedReasonApi,
                expected: 'Something failed in this session.',
            },
            {
                name: 'counts the similar sessions behind an embedding pick',
                reason: {
                    kind: 'embedding_pick',
                    watch_category: 'struggle',
                    similar_count: 1,
                } as HighlightFeedReasonApi,
                expected: 'The user struggled here and in 1\u00a0similar session.',
            },
            {
                name: 'counts sessions rather than people, so the sentence matches the similar sessions button',
                reason: {
                    kind: 'embedding_pick',
                    watch_category: 'failure',
                    similar_count: 5,
                    affected_people: 4,
                } as HighlightFeedReasonApi,
                expected: 'Something failed here and in 5\u00a0similar sessions.',
            },
            {
                name: 'renders a sentence for a reason kind this frontend does not know',
                reason: { kind: 'some_future_kind' } as unknown as HighlightFeedReasonApi,
                expected: 'Worth a look.',
            },
        ])('$name', ({ reason, expected }) => {
            expect(highlightReasonCopy(reason)).toBe(expected)
        })
    })

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

    describe('highlightStartSeconds', () => {
        it.each<{ name: string; keyMomentMs: number | null; expected: number }>([
            { name: 'starts from the beginning without a key moment', keyMomentMs: null, expected: 0 },
            { name: 'starts a few seconds before the key moment', keyMomentMs: 42_900, expected: 39 },
            { name: 'never starts before the recording', keyMomentMs: 1_000, expected: 0 },
        ])('$name', ({ keyMomentMs, expected }) => {
            expect(highlightStartSeconds(keyMomentMs)).toBe(expected)
        })
    })

    describe('highlightFeedRowSentence', () => {
        it('derives the headline from the scan prose', () => {
            const sentence = highlightFeedRowSentence(
                observation('monitor', { reasoning: 'Retried the form twice. The submit then failed.' })
            )
            expect(sentence).toBe('Retried the form twice.')
        })

        it('falls back to the scanner name when the scan wrote no prose', () => {
            const bare = {
                scanner_snapshot: { name: 'Confused checkout', scanner_type: 'monitor' },
                scanner_result: { model_output: {} },
            } as unknown as ReplayObservationApi
            expect(highlightFeedRowSentence(bare)).toBe('Confused checkout')
        })
    })

    describe('highlightFeedRowTitle', () => {
        it.each<{ name: string; scannerType: string; output: Record<string, unknown>; expected: string }>([
            {
                name: "leads with a summarizer's authored title",
                scannerType: 'summarizer',
                output: { title: 'Checkout card rejected', summary: 'Tried the card three times. Left.' },
                expected: 'Checkout card rejected',
            },
            {
                name: 'derives the headline for an untitled summarizer',
                scannerType: 'summarizer',
                output: { title: '', summary: 'Tried the card three times. Left.' },
                expected: 'Tried the card three times.',
            },
            {
                name: 'leads other scan types with the derived headline',
                scannerType: 'monitor',
                output: { reasoning: 'Retried the form twice. The submit then failed.' },
                expected: 'Retried the form twice.',
            },
        ])('$name', ({ scannerType, output, expected }) => {
            expect(highlightFeedRowTitle(observation(scannerType, output))).toBe(expected)
        })
    })

    describe('highlightCardHeadline', () => {
        it.each<{
            name: string
            scannerType: string
            output: Record<string, unknown>
            expected: ReturnType<typeof highlightCardHeadline>
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
            expect(highlightCardHeadline(observation(scannerType, output))).toEqual(expected)
        })
    })
})
