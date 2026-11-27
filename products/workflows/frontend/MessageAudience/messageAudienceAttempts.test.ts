import { PropertyFilterType, PropertyOperator } from '~/types'

import { MessageAudience, captureMessageAudienceClicked, messageAudienceUrl } from './messageAudience'
import { ATTEMPT_PREFILL_PARAM, parseAttemptPrefill } from './messageAudienceAttempts'

const audience: MessageAudience = {
    source: 'survey_respondents',
    properties: [{ key: 'id', type: PropertyFilterType.Cohort, value: 7, operator: PropertyOperator.In }],
}

const attemptIn = (url: string): string | null => new URLSearchParams(url.split('?')[1]).get(ATTEMPT_PREFILL_PARAM)

describe('message audience attempts', () => {
    it('gives each editor link the attempt of the last click on its source and destination', () => {
        expect(attemptIn(messageAudienceUrl(audience, 'broadcast'))).toBeNull()

        const broadcastClick = captureMessageAudienceClicked(audience.source, 'broadcast')
        expect(attemptIn(messageAudienceUrl(audience, 'broadcast'))).toEqual(broadcastClick)
        expect(attemptIn(messageAudienceUrl(audience, 'workflow'))).toBeNull()
        expect(attemptIn(messageAudienceUrl({ ...audience, source: 'cohort' }, 'broadcast'))).toBeNull()

        const workflowClick = captureMessageAudienceClicked(audience.source, 'workflow')
        const nextBroadcastClick = captureMessageAudienceClicked(audience.source, 'broadcast')
        expect(attemptIn(messageAudienceUrl(audience, 'workflow'))).toEqual(workflowClick)
        expect(attemptIn(messageAudienceUrl(audience, 'broadcast'))).toEqual(nextBroadcastClick)
        expect(new Set([broadcastClick, workflowClick, nextBroadcastClick]).size).toEqual(3)
    })

    it.each([
        { link: 'an attempt from a click', raw: '0190a1b2-c3d4-7e5f-8a9b-0c1d2e3f4a5b', kept: true },
        { link: 'a hand-edited attempt', raw: 'not-an-attempt', kept: false },
        { link: 'a UUID with extra text', raw: '0190a1b2-c3d4-7e5f-8a9b-0c1d2e3f4a5b-x', kept: false },
        { link: 'a repeated param', raw: ['0190a1b2-c3d4-7e5f-8a9b-0c1d2e3f4a5b'], kept: false },
    ])('keeps only a UUID for the first save: $link', ({ raw, kept }) => {
        expect(parseAttemptPrefill(raw)).toEqual(kept ? raw : undefined)
    })
})
