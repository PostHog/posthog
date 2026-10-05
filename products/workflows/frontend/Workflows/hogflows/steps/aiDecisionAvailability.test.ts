import { getAiDecisionPaletteEntry } from './aiDecisionAvailability'

describe('getAiDecisionPaletteEntry', () => {
    it.each([
        ['hidden while the flag is off', false, true, null],
        ['hidden while the flag is off, approval or not', false, false, null],
        ['offered once the flag is on and AI data processing is approved', true, true, { disabledReason: undefined }],
        [
            'shown disabled with the way to approval when AI data processing is not approved',
            true,
            false,
            {
                disabledReason:
                    "Your organization hasn't approved AI data processing yet. An admin can approve it in Organization settings, under AI service providers.",
            },
        ],
    ])('is %s', (_, flagEnabled, dataProcessingAccepted, entry) => {
        expect(getAiDecisionPaletteEntry({ flagEnabled, dataProcessingAccepted })).toEqual(entry)
    })
})
