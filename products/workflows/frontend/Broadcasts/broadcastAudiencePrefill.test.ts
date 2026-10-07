import { AnyPropertyFilter, PropertyFilterType, PropertyOperator } from '~/types'

import {
    AUDIENCE_PREFILL_PARAM,
    parseBroadcastAudiencePrefill,
    urlForNewBroadcastWithAudience,
} from './broadcastAudiencePrefill'

const COHORT_AUDIENCE: AnyPropertyFilter[] = [
    { key: 'id', type: PropertyFilterType.Cohort, value: 7, operator: PropertyOperator.In },
]

describe('broadcastAudiencePrefill', () => {
    it('round-trips an audience through the URL', () => {
        const url = urlForNewBroadcastWithAudience({ properties: COHORT_AUDIENCE, source: 'cohort' })
        const raw = new URLSearchParams(url.split('?')[1]).get(AUDIENCE_PREFILL_PARAM)

        expect(parseBroadcastAudiencePrefill(raw)).toEqual(COHORT_AUDIENCE)
    })

    it.each([
        ['nothing', undefined],
        ['a non-JSON string', 'not-json'],
        ['an empty audience', '[]'],
        ['an object instead of a list', '{"key":"email"}'],
        ['an event filter, which a broadcast audience cannot use', '[{"key":"$browser","type":"event","value":"x"}]'],
        ['a person filter missing its value', '[{"key":"email","type":"person","operator":"exact"}]'],
        ['a cohort filter without a cohort id', '[{"key":"id","type":"cohort","operator":"in"}]'],
        [
            'one bad filter next to a good one',
            '[{"key":"id","type":"cohort","value":7},{"key":"email","type":"person","operator":"exact","value":[]}]',
        ],
    ])('returns null for %s', (_label, raw) => {
        expect(parseBroadcastAudiencePrefill(raw)).toBeNull()
    })

    it('accepts a person filter that needs no value', () => {
        const audience = [{ key: 'email', type: PropertyFilterType.Person, operator: PropertyOperator.IsSet }]

        expect(parseBroadcastAudiencePrefill(JSON.stringify(audience))).toEqual(audience)
    })
})
