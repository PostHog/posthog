import type { ReplayObservationApi, WatchFeedReasonApi } from '../../generated/api.schemas'
import {
    jevCardContext,
    jevCardSentence,
    jevTileText,
    observationKeyMomentMs,
    watchCardHeadline,
    watchReasonCopy,
    watchStartSeconds,
} from './WatchFeedCard'

describe('WatchFeedCard helpers', () => {
    describe('watchReasonCopy', () => {
        it.each<{ name: string; reason: WatchFeedReasonApi; expected: string }>([
            {
                name: 'counts signals on a session scanned before headlines shipped',
                reason: { kind: 'signal_emitted', signals_count: 3 } as WatchFeedReasonApi,
                expected: 'The scanner raised 3 signals from this session.',
            },
            {
                name: 'names a single signal problem type',
                reason: { kind: 'signal_emitted', signals_count: 1, problem_types: ['bug'] } as WatchFeedReasonApi,
                expected: 'The scanner raised a bug signal from this session.',
            },
            {
                name: 'names and counts one repeated problem type',
                reason: {
                    kind: 'signal_emitted',
                    signals_count: 3,
                    problem_types: ['bug', 'bug', 'bug'],
                } as WatchFeedReasonApi,
                expected: 'The scanner raised 3 bug signals from this session.',
            },
            {
                name: 'breaks mixed problem types down by count',
                reason: {
                    kind: 'signal_emitted',
                    signals_count: 2,
                    problem_types: ['bug', 'ux_friction'],
                } as WatchFeedReasonApi,
                expected: 'The scanner raised 2 signals from this session: 1 bug signal, 1 UX friction signal.',
            },
            {
                name: 'pluralizes and orders each type in a mixed breakdown',
                reason: {
                    kind: 'signal_emitted',
                    signals_count: 3,
                    problem_types: ['bug', 'bug', 'ux_friction'],
                } as WatchFeedReasonApi,
                expected: 'The scanner raised 3 signals from this session: 2 bug signals, 1 UX friction signal.',
            },
            {
                name: 'names the finding behind a single signal',
                reason: {
                    kind: 'signal_emitted',
                    signals_count: 1,
                    problem_types: ['bug'],
                    signals: [{ problem_type: 'bug', headline: 'Checkout button does nothing' }],
                } as WatchFeedReasonApi,
                expected: 'The scanner raised a bug signal from this session: Checkout button does nothing.',
            },
            {
                name: 'lists the findings when one type raised several',
                reason: {
                    kind: 'signal_emitted',
                    signals_count: 2,
                    problem_types: ['bug', 'bug'],
                    signals: [
                        { problem_type: 'bug', headline: 'Checkout button does nothing' },
                        { problem_type: 'bug', headline: 'Card form rejects a valid card' },
                    ],
                } as WatchFeedReasonApi,
                expected:
                    'The scanner raised 2 bug signals from this session: Checkout button does nothing, and Card form rejects a valid card.',
            },
            {
                name: 'groups the findings under each type in a mixed breakdown',
                reason: {
                    kind: 'signal_emitted',
                    signals_count: 3,
                    problem_types: ['bug', 'bug', 'ux_friction'],
                    signals: [
                        { problem_type: 'bug', headline: 'Checkout button does nothing' },
                        { problem_type: 'bug', headline: 'Card form rejects a valid card' },
                        { problem_type: 'ux_friction', headline: 'Search results load twice' },
                    ],
                } as WatchFeedReasonApi,
                expected:
                    'The scanner raised 3 signals from this session: 2 bug (Checkout button does nothing, Card form rejects a valid card), and 1 UX friction (Search results load twice).',
            },
            {
                name: 'counts the findings it has no room to name',
                reason: {
                    kind: 'signal_emitted',
                    signals_count: 5,
                    problem_types: ['bug', 'bug', 'bug', 'bug', 'bug'],
                    signals: [
                        { problem_type: 'bug', headline: 'Checkout button does nothing' },
                        { problem_type: 'bug', headline: 'Card form rejects a valid card' },
                        { problem_type: 'bug', headline: 'Order total shows zero' },
                        { problem_type: 'bug', headline: 'Address lookup returns nothing' },
                        { problem_type: 'bug', headline: 'Receipt page is blank' },
                    ],
                } as WatchFeedReasonApi,
                expected:
                    'The scanner raised 5 bug signals from this session: Checkout button does nothing, Card form rejects a valid card, Order total shows zero, and 2 more.',
            },
            {
                name: 'rounds the score and window average',
                reason: { kind: 'outlier_score', score: 9.53846, window_mean: 5.1428 } as WatchFeedReasonApi,
                expected: "Scored 9.54, far from this scanner's recent average of 5.14.",
            },
            {
                name: 'falls back when an outlier_score arrives without its numbers',
                reason: { kind: 'outlier_score' } as WatchFeedReasonApi,
                expected: "Scored far from this scanner's recent average.",
            },
            {
                name: 'falls back when an unusual_verdict arrives without a verdict',
                reason: { kind: 'unusual_verdict' } as WatchFeedReasonApi,
                expected: 'The scanner gave a rare answer for this window.',
            },
            {
                name: 'falls back when a rare_tag arrives without a tag',
                reason: { kind: 'rare_tag' } as WatchFeedReasonApi,
                expected: 'Tagged something uncommon for this scanner lately.',
            },
            {
                name: 'renders a sentence for a reason kind this frontend does not know',
                reason: { kind: 'some_future_kind' } as unknown as WatchFeedReasonApi,
                expected: 'Worth a look.',
            },
        ])('$name', ({ reason, expected }) => {
            expect(watchReasonCopy(reason)).toBe(expected)
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

    describe('watchStartSeconds', () => {
        it.each<{ name: string; keyMomentMs: number | null; expected: number }>([
            { name: 'starts from the beginning without a key moment', keyMomentMs: null, expected: 0 },
            { name: 'starts a few seconds before the key moment', keyMomentMs: 42_900, expected: 39 },
            { name: 'never starts before the recording', keyMomentMs: 1_000, expected: 0 },
        ])('$name', ({ keyMomentMs, expected }) => {
            expect(watchStartSeconds(keyMomentMs)).toBe(expected)
        })
    })

    describe('jevCardSentence', () => {
        it("prefers the scan's notability sentence over the derived headline", () => {
            const sentence = jevCardSentence(
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
            const sentence = jevCardSentence(
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
            expect(jevCardSentence(bare, { kind: 'unviewed_recent' } as WatchFeedReasonApi)).toBe('Confused checkout')
        })
    })

    describe('jevCardContext', () => {
        it('gives the whole derived narration when the notability sentence leads', () => {
            const context = jevCardContext(
                observation('monitor', { reasoning: 'Retried the form twice. The submit then failed.' }),
                {
                    kind: 'jev_watchable',
                    jev_probability: 0.9,
                    notability_reason: 'The card form rejected a valid card three times.',
                } as WatchFeedReasonApi
            )
            expect(context).toBe('Retried the form twice. The submit then failed.')
        })

        it('never repeats the lead sentence when the derived headline leads', () => {
            const context = jevCardContext(
                observation('monitor', { reasoning: 'Retried the form twice. The submit then failed.' }),
                { kind: 'jev_watchable', jev_probability: 0.9 } as WatchFeedReasonApi
            )
            expect(context).toBe('The submit then failed.')
        })

        it('gives a filler row no context, so it stays small', () => {
            const context = jevCardContext(
                observation('monitor', { reasoning: 'Retried the form twice. The submit then failed.' }),
                { kind: 'unviewed_recent' } as WatchFeedReasonApi
            )
            expect(context).toBeNull()
        })
    })

    describe('jevTileText', () => {
        it.each<{
            name: string
            scannerType: string
            output: Record<string, unknown>
            reason: WatchFeedReasonApi
            expected: ReturnType<typeof jevTileText>
        }>([
            {
                name: "leads with a summarizer's authored title and moves the scan's sentence to the detail",
                scannerType: 'summarizer',
                output: { title: 'Checkout card rejected', summary: 'Tried the card three times. Left.' },
                reason: {
                    kind: 'jev_watchable',
                    jev_probability: 0.9,
                    notability_reason: 'The card form rejected a valid card three times.',
                } as WatchFeedReasonApi,
                expected: {
                    title: 'Checkout card rejected',
                    detail: 'The card form rejected a valid card three times.',
                },
            },
            {
                name: 'falls back to the summary for the detail when the scan wrote no sentence',
                scannerType: 'summarizer',
                output: { title: 'Checkout card rejected', summary: 'Tried the card three times. Left.' },
                reason: { kind: 'jev_watchable', jev_probability: 0.9 } as WatchFeedReasonApi,
                expected: { title: 'Checkout card rejected', detail: 'Tried the card three times. Left.' },
            },
            {
                name: 'gives a filler summarizer tile no detail',
                scannerType: 'summarizer',
                output: { title: 'Checkout card rejected', summary: 'Tried the card three times. Left.' },
                reason: { kind: 'unviewed_recent' } as WatchFeedReasonApi,
                expected: { title: 'Checkout card rejected', detail: null },
            },
            {
                name: 'leads other scan types with the card sentence and reveals the unused narration',
                scannerType: 'monitor',
                output: { reasoning: 'Retried the form twice. The submit then failed.' },
                reason: { kind: 'jev_watchable', jev_probability: 0.9 } as WatchFeedReasonApi,
                expected: { title: 'Retried the form twice.', detail: 'The submit then failed.' },
            },
        ])('$name', ({ scannerType, output, reason, expected }) => {
            expect(jevTileText(observation(scannerType, output), reason)).toEqual(expected)
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
