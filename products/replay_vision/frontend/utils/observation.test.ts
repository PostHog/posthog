import type { ReplayObservationApi } from '../generated/api.schemas'
import { observationClipboardText } from './observation'

function makeObservation(
    scannerType: string,
    modelOutput: Record<string, unknown> | null,
    status: ReplayObservationApi['status'] = 'succeeded'
): ReplayObservationApi {
    return {
        id: 'obs-1',
        session_id: 'sess-1',
        status,
        created_at: '2026-07-27T10:00:00Z',
        scanner_snapshot: { scanner_type: scannerType },
        scanner_result: modelOutput ? { model_output: modelOutput } : null,
    } as unknown as ReplayObservationApi
}

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
