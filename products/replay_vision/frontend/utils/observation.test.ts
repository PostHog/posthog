import type { ReplayObservationApi } from '../generated/api.schemas'
import { ObservationSeekbarMark, observationClipboardText, observationSeekbarMarks } from './observation'

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
                    { timestampMs: 30_000, scannerNames: ['Session summarizer'] },
                    { timestampMs: 161_000, scannerNames: ['Session summarizer'] },
                ],
            },
            {
                name: 'monitor: leaked (t N) markers in reasoning are parsed client-side',
                observations: [
                    makeObservation(
                        'monitor',
                        { verdict: 'yes', reasoning: 'Error toast shown (t 42).' },
                        'succeeded',
                        'Error monitor'
                    ),
                ],
                expected: [{ timestampMs: 42_000, scannerNames: ['Error monitor'] }],
            },
            {
                name: 'two scanners citing the same moment merge into one mark',
                observations: [
                    makeObservation('monitor', { reasoning: 'Saw it (t 42).' }, 'succeeded', 'Monitor A'),
                    makeObservation('scorer', { reasoning: 'Also saw it (t 42).' }, 'succeeded', 'Scorer B'),
                ],
                expected: [{ timestampMs: 42_000, scannerNames: ['Monitor A', 'Scorer B'] }],
            },
            {
                name: 'non-succeeded observations contribute no marks',
                observations: [makeObservation('monitor', { reasoning: 'Saw it (t 42).' }, 'failed')],
                expected: [],
            },
        ])('$name', ({ observations, expected }) => {
            expect(observationSeekbarMarks(observations)).toEqual(expected)
        })
    })
})
