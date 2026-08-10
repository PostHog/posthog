import type { ScanOutcomeEnumApi } from '../generated/api.schemas'
import { summarizeOutcomeMessage } from './summarizeRecording'

describe('summarizeRecording', () => {
    // The inline scan answers 202 even when it started nothing, so an outcome that falls through to a
    // success toast tells the user a summary is coming when the quota or the in-flight cap refused it.
    it.each<[ScanOutcomeEnumApi | undefined, 'success' | 'info' | 'error']>([
        ['started', 'success'],
        ['already_scanned', 'info'],
        ['already_running', 'info'],
        ['skipped_quota', 'error'],
        ['skipped_limit', 'error'],
        ['failed', 'error'],
        [undefined, 'error'],
    ])('reports %s as %s', (outcome, level) => {
        expect(summarizeOutcomeMessage(outcome).level).toBe(level)
    })
})
