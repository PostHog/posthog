import type { ReplayObservationApi } from '../generated/api.schemas'
import {
    ObservationSeekbarMark,
    dockObservations,
    observationClipboardText,
    observationSeekbarMarks,
    scannerLabel,
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
                // A one-off summarize is the scan most likely to cite a timestamp, and its scanner has
                // no name. Passing the raw name through leaves the tooltip line blank, because a
                // summarizer has no headline to fall back on either.
                name: 'a quick summary labels its mark rather than leaving it blank',
                observations: [
                    {
                        ...makeObservation('summarizer', {
                            summary: 'Rage clicked pay',
                            summary_segments: [
                                { kind: 'text', value: 'Rage clicked pay' },
                                { kind: 'chip', timestamp_ms: 42_000 },
                            ],
                        }),
                        scanner_origin: 'inline',
                        scanner_snapshot: { scanner_type: 'summarizer', name: '' },
                    } as unknown as ReplayObservationApi,
                ],
                expected: [
                    {
                        timestampMs: 42_000,
                        entries: [{ scannerName: 'Quick summary', headline: null, snippet: 'Rage clicked pay' }],
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

    describe('scannerLabel', () => {
        // A one-off scan's scanner is unnamed, so falling back to the snapshot name renders a blank
        // label in the player dock, the sidebar, and search, which are the surfaces that flow is made of.
        // The name it gets instead has to be the dock's own word for the thing the person clicked.
        const scanned = (scannerOrigin: string, scannerType: string, scannerName: string): ReplayObservationApi =>
            ({
                ...makeObservation(scannerType, null, 'succeeded', scannerName),
                scanner_origin: scannerOrigin,
            }) as unknown as ReplayObservationApi

        it.each<[string, string, string, string, string]>([
            ['a saved scanner uses its name', 'configured', 'monitor', 'Ghost bugs', 'Ghost bugs'],
            ['the dock summarize button answers to its own label', 'inline', 'summarizer', '', 'Quick summary'],
            ['a one-off scan that is not a summary stays generic', 'inline', 'monitor', '', 'One-off scan'],
            ['an unnamed saved scanner still reads as a scanner', 'configured', 'monitor', '', 'Scanner'],
        ])('%s', (_, scannerOrigin, scannerType, scannerName, expected) => {
            expect(scannerLabel(scanned(scannerOrigin, scannerType, scannerName))).toBe(expected)
        })
    })
})
