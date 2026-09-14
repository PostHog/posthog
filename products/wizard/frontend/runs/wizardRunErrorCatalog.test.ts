import { wizardRunErrorDetails } from './wizardRunErrorCatalog'

describe('wizardRunErrorDetails', () => {
    it('returns guidance for a catalogued Wizard error', () => {
        expect(wizardRunErrorDetails('PHW_DETECT_NO_POSTHOG_SDK', null)).toEqual({
            title: 'No PostHog SDK was found',
            description: 'This program needs an existing PostHog SDK installation.',
            resolution:
                'Run the PostHog integration program first, merge its pull request, then run this program again.',
        })
    })

    it('returns guidance for a detect-stage failure with no SDKs', () => {
        expect(wizardRunErrorDetails('PHW_DETECT_NO_SDKS', null).title).toBe('No PostHog or Stripe SDK was found')
        expect(wizardRunErrorDetails('PHW_DETECT_NO_PACKAGE_JSON', null).title).toBe('No package.json was found')
        expect(wizardRunErrorDetails('PHW_DETECT_MISSING_STRIPE', null).title).toBe('No Stripe SDK was found')
        expect(wizardRunErrorDetails('PHW_DETECT_UNCLASSIFIED', null).title).toBe(
            'The Wizard could not inspect this project'
        )
    })

    it('uses the safe backend message for an unknown error', () => {
        expect(wizardRunErrorDetails('PHW_FUTURE_ERROR', 'The Wizard could not finish.')).toEqual({
            title: 'The Wizard could not finish.',
            description: 'The Wizard could not finish.',
        })
    })
})
