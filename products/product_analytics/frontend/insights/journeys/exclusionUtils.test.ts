import { PathsV2Item, PathsV2StepSource } from '~/queries/schema/schema-general'

import { excludedLabelsForSource, staleExcludedItems, withExcludedLabels } from './exclusionUtils'

const pageviews: PathsV2StepSource = { event: '$pageview', namingProperty: '$pathname' }
const screens: PathsV2StepSource = { event: '$screen', namingProperty: '$screen_name' }
const signup: PathsV2StepSource = { event: 'signup' }

describe('journeys exclusion utils', () => {
    const excluded: PathsV2Item[] = [
        { event: '$pageview', label: '/login' },
        { event: '$screen', label: 'Login' },
        { event: 'signup' },
        { event: 'gone', label: '/x' },
    ]

    it('lists only the labels editable through the given source', () => {
        expect(excludedLabelsForSource(excluded, pageviews)).toEqual(['/login'])
    })

    it("replaces one source's labels without touching other exclusions", () => {
        expect(withExcludedLabels(excluded, pageviews, ['/logout'])).toEqual([
            { event: '$screen', label: 'Login' },
            { event: 'signup' },
            { event: 'gone', label: '/x' },
            { event: '$pageview', label: '/logout' },
        ])
    })

    it('flags exclusions no exclusion row can edit as stale', () => {
        expect(staleExcludedItems(excluded, [pageviews, screens, signup])).toEqual([
            { event: 'signup' },
            { event: 'gone', label: '/x' },
        ])
    })
})
