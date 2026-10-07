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
    ])('returns null for %s', (_label, raw) => {
        expect(parseBroadcastAudiencePrefill(raw)).toBeNull()
    })
})
