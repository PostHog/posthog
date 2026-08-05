import { PathsV2Anchor, PathsV2AnchorType, PathsV2StepSource } from '~/queries/schema/schema-general'

import { anchorSurvivesStepSources, exclusionsWithoutAnchor } from './anchorUtils'

const anchor = (event: string, label?: string | null): PathsV2Anchor => ({
    type: PathsV2AnchorType.Start,
    item: label === undefined ? { event } : { event, label },
})

describe('anchorUtils', () => {
    describe('anchorSurvivesStepSources', () => {
        const pageviews: PathsV2StepSource[] = [{ event: '$pageview', namingProperty: '$pathname' }]
        const screens: PathsV2StepSource[] = [{ event: '$screen', namingProperty: '$screen_name' }]
        const eventOnly: PathsV2StepSource[] = [{ event: 'signup' }]

        test.each<[string, PathsV2Anchor, PathsV2StepSource[], boolean]>([
            ['a labelled anchor survives its unchanged naming source', anchor('$pageview', '/home'), pageviews, true],
            ['an empty label counts as a label on a naming source', anchor('$pageview', ''), pageviews, true],
            ['an event-only anchor survives its event-only source', anchor('signup'), eventOnly, true],
            ['the anchor event is no longer a step source', anchor('$pageview', '/home'), screens, false],
            [
                'the anchor source gained a naming property but the anchor has no label',
                anchor('$pageview'),
                pageviews,
                false,
            ],
            [
                'the anchor source lost its naming property but the anchor keeps a label',
                anchor('signup', '/home'),
                eventOnly,
                false,
            ],
        ])('%s', (_name, candidate, stepSources, expected) => {
            expect(anchorSurvivesStepSources(candidate, stepSources)).toEqual(expected)
        })
    })

    describe('exclusionsWithoutAnchor', () => {
        it('strips items deriving to the anchor, treating a missing label as an empty one', () => {
            const excluded = [
                { event: '$pageview', label: '/home' },
                { event: '$pageview', label: '/pricing' },
                { event: 'signup' },
            ]
            expect(exclusionsWithoutAnchor(excluded, anchor('$pageview', '/home'))).toEqual({
                items: [{ event: '$pageview', label: '/pricing' }, { event: 'signup' }],
                removed: true,
            })
            // The backend matches (event, label or ''): a label-less exclusion equals a label-less anchor
            expect(exclusionsWithoutAnchor(excluded, anchor('signup', null))).toEqual({
                items: [
                    { event: '$pageview', label: '/home' },
                    { event: '$pageview', label: '/pricing' },
                ],
                removed: true,
            })
        })

        it('reports no removal when nothing collides', () => {
            const excluded = [{ event: '$pageview', label: '/pricing' }]
            expect(exclusionsWithoutAnchor(excluded, anchor('$pageview', '/home'))).toEqual({
                items: excluded,
                removed: false,
            })
        })
    })
})
