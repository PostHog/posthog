import { archiveDisabledReason } from './broadcastLifecycle'

describe('archiveDisabledReason', () => {
    it.each([
        { runs: 'runs not loaded yet', statuses: null, blocked: true },
        { runs: 'no runs', statuses: [], blocked: false },
        { runs: 'a finished and a failed run', statuses: ['completed', 'failed'], blocked: false },
        { runs: 'rows whose runs have not loaded', statuses: [undefined], blocked: false },
        { runs: 'a queued run', statuses: ['queued'], blocked: true },
        { runs: 'an older run still sending', statuses: ['completed', 'active'], blocked: true },
    ])('with $runs blocks archiving: $blocked', ({ statuses, blocked }) => {
        expect(!!archiveDisabledReason(statuses)).toBe(blocked)
    })
})
