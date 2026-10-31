import { newScanner } from './newScanner'

describe('newScanner', () => {
    it('starts a blank monitor with the expected defaults', () => {
        expect(newScanner()).toMatchObject({
            id: 'new',
            enabled: true,
            scanner_type: 'monitor',
            scanner_config: { prompt: '' },
            name: 'New monitor',
            // Narrow by default so the budget step's first estimate isn't a whole-project number.
            sampling_rate: 0.2,
            sampling_mode: 'balanced',
            description: '',
            tags: [],
        })
    })
})
