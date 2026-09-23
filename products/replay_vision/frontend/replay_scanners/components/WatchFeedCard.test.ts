import type { ReplayObservationApi, WatchFeedReasonApi } from '../../generated/api.schemas'
import { observationClipRange, watchReasonCopy } from './WatchFeedCard'

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

    describe('observationClipRange', () => {
        const observation = (scannerType: string | undefined, output: Record<string, unknown>): ReplayObservationApi =>
            ({
                scanner_snapshot: scannerType ? { scanner_type: scannerType } : undefined,
                scanner_result: { model_output: output },
            }) as unknown as ReplayObservationApi

        it('reads the summary citation when the snapshot type is summarizer, even if the result omits scanner_type', () => {
            const range = observationClipRange(
                observation('summarizer', {
                    summary: 'Wrapped up (t 30) cleanly.',
                    reasoning: 'Debugged (t 90) at length.',
                })
            )
            expect(range).toEqual({ startMs: 30_000, endMs: 30_000 })
        })

        it('reads the reasoning citation for a non-summarizer type', () => {
            const range = observationClipRange(observation('monitor', { reasoning: 'Retried (t 45) twice.' }))
            expect(range).toEqual({ startMs: 45_000, endMs: 45_000 })
        })
    })
})
