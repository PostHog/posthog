import type { ReplayObservationApi } from '../generated/api.schemas'
import {
    ObservationSeekbarMark,
    dockObservations,
    observationClipboardText,
    observationSeekbarMarks,
} from './observation'

const summarizerEntry = { scannerName: 'Session summarizer', headline: null, snippet: 'Rage clicked pay' }
const longSentence = 'x'.repeat(200)

function makeObservation(
    scannerType: string,
    modelOutput: Record<string, unknown> | null,
    status: ReplayObservationApi['status'] = 'succeeded',
    scannerName: string = 'Scanner'
): ReplayObservationApi {
    return {
        id: 'obs-1',
        session_id: 'sess-1',
        status,
        created_at: '2026-07-27T10:00:00Z',
        scanner_snapshot: { scanner_type: scannerType, name: scannerName },
        scanner_result: modelOutput ? { model_output: modelOutput } : null,
    } as unknown as ReplayObservationApi
}

describe('observation utils', () => {
    describe('observationClipboardText', () => {
        it.each<{ name: string; obs: ReplayObservationApi; expected: string | null }>([
            {
                name: 'summarizer: title headline, summary body with citations as plain timestamps',
                obs: makeObservation('summarizer', { title: 'Checkout rage', summary: 'Rage clicked pay (t 161).' }),
                expected: '[2026-07-27 · sess-1] Checkout rage\nRage clicked pay (02:41).',
            },
            {
                name: 'monitor: verdict headline, reasoning body',
                obs: makeObservation('monitor', { verdict: 'yes', reasoning: 'Error toast shown.' }),
                expected: '[2026-07-27 · sess-1] Verdict: yes\nError toast shown.',
            },
            {
                name: 'failed observations are excluded',
                obs: makeObservation('monitor', { verdict: 'yes' }, 'failed'),
                expected: null,
            },
            {
                name: 'no output yields nothing',
                obs: makeObservation('summarizer', null),
                expected: null,
            },
        ])('$name', ({ obs, expected }) => {
            expect(observationClipboardText(obs)).toBe(expected)
        })
    })

    describe('observationSeekbarMarks', () => {
        it.each<{ name: string; observations: ReplayObservationApi[]; expected: ObservationSeekbarMark[] }>([
            {
                name: 'summarizer: persisted citation segments become marks, deduped and ascending',
                observations: [
                    makeObservation(
                        'summarizer',
                        {
                            summary: 'Rage clicked pay',
                            summary_segments: [
                                { kind: 'text', value: 'Rage clicked pay' },
                                { kind: 'chip', timestamp_ms: 161_000 },
                                { kind: 'chip', timestamp_ms: 30_000 },
                                { kind: 'chip', timestamp_ms: 161_000 },
                            ],
                        },
                        'succeeded',
                        'Session summarizer'
                    ),
                ],
                expected: [
                    { timestampMs: 30_000, entries: [summarizerEntry] },
                    { timestampMs: 161_000, entries: [summarizerEntry] },
                ],
            },
            {
                name: 'monitor: leaked (t N) markers parsed client-side, verdict headline, citing sentence as snippet',
                observations: [
                    makeObservation(
                        'monitor',
                        { verdict: 'yes', reasoning: 'User opened checkout. Error toast shown (t 42).' },
                        'succeeded',
                        'Error monitor'
                    ),
                ],
                expected: [
                    {
                        timestampMs: 42_000,
                        entries: [
                            {
                                scannerName: 'Error monitor',
                                headline: 'Verdict: yes',
                                snippet: 'Error toast shown',
                            },
                        ],
                    },
                ],
            },
            {
                name: 'two scanners citing the same moment merge into one mark',
                observations: [
                    makeObservation('monitor', { reasoning: 'Saw it (t 42).' }, 'succeeded', 'Monitor A'),
                    makeObservation('scorer', { score: 3, reasoning: 'Also saw it (t 42).' }, 'succeeded', 'Scorer B'),
                ],
                expected: [
                    {
                        timestampMs: 42_000,
                        entries: [
                            { scannerName: 'Monitor A', headline: null, snippet: 'Saw it' },
                            { scannerName: 'Scorer B', headline: 'Score: 3', snippet: 'Also saw it' },
                        ],
                    },
                ],
            },
            {
                name: 'non-succeeded observations contribute no marks',
                observations: [makeObservation('monitor', { reasoning: 'Saw it (t 42).' }, 'failed')],
                expected: [],
            },
            {
                name: 'snippets longer than 160 characters are truncated with an ellipsis',
                observations: [makeObservation('monitor', { reasoning: `${longSentence} (t 42).` })],
                expected: [
                    {
                        timestampMs: 42_000,
                        entries: [
                            { scannerName: 'Scanner', headline: null, snippet: `${longSentence.slice(0, 159)}…` },
                        ],
                    },
                ],
            },
            {
                name: 'output without citations yields no marks',
                observations: [makeObservation('monitor', { verdict: 'yes', reasoning: 'Error toast shown.' })],
                expected: [],
            },
            {
                name: 'citation with no preceding text yields a null snippet',
                observations: [
                    makeObservation('summarizer', {
                        summary: 'Rage clicked pay',
                        summary_segments: [{ kind: 'chip', timestamp_ms: 42_000 }],
                    }),
                ],
                expected: [
                    { timestampMs: 42_000, entries: [{ scannerName: 'Scanner', headline: null, snippet: null }] },
                ],
            },
        ])('$name', ({ observations, expected }) => {
            expect(observationSeekbarMarks(observations)).toEqual(expected)
        })
    })

    describe('dockObservations', () => {
        const obs = (
            id: string,
            scannerType: string,
            status: ReplayObservationApi['status']
        ): ReplayObservationApi => ({ ...makeObservation(scannerType, null, status), id })

        // The dock is the only vision surface under the player, and a scan that settled without a
        // result is exactly what a person needs it for: nothing else there says why none arrived.
        // Succeeded scanner runs stay in the sidebar, so the dock does not restate what it already has.
        it.each<[string, ReplayObservationApi[], string[]]>([
            ['a summary is shown', [obs('s1', 'summarizer', 'succeeded')], ['s1']],
            ['a failed summary is shown once, not twice', [obs('s1', 'summarizer', 'failed')], ['s1']],
            ['a failed scanner is shown', [obs('m1', 'monitor', 'failed')], ['m1']],
            ['an ineligible scanner is shown', [obs('m1', 'monitor', 'ineligible')], ['m1']],
            ['a succeeded scanner stays in the sidebar', [obs('m1', 'monitor', 'succeeded')], []],
            ['a running scanner stays in the sidebar', [obs('m1', 'monitor', 'running')], []],
            [
                'summaries come before scans that left no result',
                [obs('m1', 'monitor', 'failed'), obs('s1', 'summarizer', 'succeeded')],
                ['s1', 'm1'],
            ],
        ])('%s', (_, observations, expectedIds) => {
            expect(dockObservations(observations).map((o) => o.id)).toEqual(expectedIds)
        })
    })
})
