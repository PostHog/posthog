import { PathsV2Item, PathsV2StepSource } from '~/queries/schema/schema-general'

import { excludedItemChips, excludedLabelsForSource, withExcludedLabels } from './exclusionUtils'

const pageviews: PathsV2StepSource = { event: '$pageview', namingProperty: '$pathname' }
const screens: PathsV2StepSource = { event: '$screen', namingProperty: '$screen_name' }
const signup: PathsV2StepSource = { event: 'signup' }

describe('journeys exclusion utils', () => {
    const excluded: PathsV2Item[] = [
        { event: '$pageview', label: '/login' },
        { event: '$screen', label: 'Login' },
        { event: '$pageview' },
        { event: 'signup' },
        { event: 'signup', label: 'x' },
        { event: 'gone', label: '/x' },
    ]

    it('lists only the labels editable through the given source', () => {
        expect(excludedLabelsForSource(excluded, pageviews)).toEqual(['/login'])
    })

    it("replaces one source's labels without touching other exclusions", () => {
        expect(withExcludedLabels(excluded, pageviews, ['/logout'])).toEqual([
            { event: '$screen', label: 'Login' },
            { event: '$pageview' },
            { event: 'signup' },
            { event: 'signup', label: 'x' },
            { event: 'gone', label: '/x' },
            { event: '$pageview', label: '/logout' },
        ])
    })

    it('splits chip exclusions into applied and inert exactly as the backend matches them', () => {
        expect(excludedItemChips(excluded, [pageviews, screens, signup])).toEqual({
            // (event, '') items: the whole signup event, and pageviews with no pathname.
            active: [{ event: '$pageview' }, { event: 'signup' }],
            // No derivable item can equal these: a labeled item of a label-less source, an unknown event.
            inert: [
                { event: 'signup', label: 'x' },
                { event: 'gone', label: '/x' },
            ],
        })
    })
})
