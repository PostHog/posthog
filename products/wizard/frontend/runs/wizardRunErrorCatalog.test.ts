import { wizardRunErrorDetails } from './wizardRunErrorCatalog'

describe('wizardRunErrorDetails', () => {
    it('returns guidance for a catalogued Wizard error', () => {
        expect(wizardRunErrorDetails('PHW_DETECT_NO_POSTHOG_SDK', null)).toEqual({
            title: 'No PostHog SDK was found',
            description: 'This program needs an existing PostHog SDK installation.',
            resolution: 'Run the PostHog integration program first, then run this program again.',
        })
    })

    it('uses the safe backend message for an unknown error', () => {
        expect(wizardRunErrorDetails('PHW_FUTURE_ERROR', 'The Wizard could not finish.')).toEqual({
            title: 'The Wizard could not finish.',
            description: 'The Wizard could not finish.',
        })
    })
})
