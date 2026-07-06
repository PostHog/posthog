import type { ScannerParametersApi } from '../generated/api.schemas'
import { hasParameterChanges, suggestionParameterChanges } from './suggestionParameterDiff'

describe('suggestionParameterChanges', () => {
    const base: ScannerParametersApi = {
        scanner_config: { prompt: 'tag the session', tags: ['bug', 'confusion'] },
        query: { kind: 'RecordingsQuery', filter_test_accounts: true },
        sampling_rate: 0.5,
    }

    it('returns null for legacy prompt-only suggestions', () => {
        expect(suggestionParameterChanges({ base_parameters: null, suggested_parameters: null })).toBeNull()
    })

    it('computes vocabulary and sampling rate changes', () => {
        const changes = suggestionParameterChanges({
            base_parameters: base,
            suggested_parameters: {
                scanner_config: { prompt: 'tag the session', tags: ['bug', 'churn'] },
                query: base.query,
                sampling_rate: 0.25,
            },
        })
        expect(changes).not.toBeNull()
        expect(changes!.tagsAdded).toEqual(['churn'])
        expect(changes!.tagsRemoved).toEqual(['confusion'])
        expect(changes!.samplingRate).toEqual({ before: 0.5, after: 0.25 })
        expect(changes!.queryChanged).toBe(false)
        expect(changes!.configChanged).toBe(true)
        expect(hasParameterChanges(changes!)).toBe(true)
    })

    it('ignores key order when comparing the recordings filter', () => {
        // The base comes from the scanner row and the proposal from LLM JSON, so key order differs
        // even when nothing changed; that must not read as a filter change.
        const changes = suggestionParameterChanges({
            base_parameters: base,
            suggested_parameters: {
                ...base,
                query: { filter_test_accounts: true, kind: 'RecordingsQuery' },
            },
        })
        expect(changes!.queryChanged).toBe(false)
        expect(hasParameterChanges(changes!)).toBe(false)
    })

    it('flags trigger-only suggestions as leaving per-session behavior unchanged', () => {
        const changes = suggestionParameterChanges({
            base_parameters: base,
            suggested_parameters: { ...base, sampling_rate: 0.1 },
        })
        expect(changes!.configChanged).toBe(false)
        expect(hasParameterChanges(changes!)).toBe(true)
    })
})
