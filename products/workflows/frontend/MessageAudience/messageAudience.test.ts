import posthog from 'posthog-js'

import { PropertyFilterType, PropertyOperator } from '~/types'

import {
    MessageAudience,
    MessageAudienceDestination,
    captureMessageAudienceClicked,
    captureMessageAudienceShown,
    messageAudienceUrl,
} from './messageAudience'

function audienceFrom(source: string): MessageAudience {
    return {
        source,
        properties: [{ key: 'id', type: PropertyFilterType.Cohort, value: 7, operator: PropertyOperator.In }],
    }
}

function attemptInUrl(source: string, destination: MessageAudienceDestination): string | null {
    return new URL(messageAudienceUrl(audienceFrom(source), destination), 'https://app.example.com').searchParams.get(
        'attempt'
    )
}

describe('message audience attempts', () => {
    let capture: jest.SpyInstance

    beforeEach(() => {
        capture = jest.spyOn(posthog, 'capture').mockImplementation(() => undefined)
    })

    afterEach(() => {
        capture.mockRestore()
    })

    function captured(event: string): Record<string, unknown>[] {
        return capture.mock.calls.filter(([name]) => name === event).map(([, properties]) => properties)
    }

    it('reports a spot shown once, and carries its attempt through the click into the editor URL', () => {
        captureMessageAudienceShown('early_access', 'workflow')
        captureMessageAudienceShown('early_access', 'workflow')
        captureMessageAudienceClicked('early_access', 'workflow')

        const [shown, ...repeated] = captured('message audience shown')
        expect(repeated).toEqual([])
        expect(shown).toEqual({ source: 'early_access', destination: 'workflow', attempt_id: expect.any(String) })
        expect(captured('message audience clicked')).toEqual([
            { source: 'early_access', destination: 'workflow', attempt_id: shown.attempt_id },
        ])
        expect(attemptInUrl('early_access', 'workflow')).toEqual(shown.attempt_id)
    })

    it('gives each destination of one source its own attempt', () => {
        captureMessageAudienceShown('cohort', 'broadcast')
        captureMessageAudienceShown('cohort', 'workflow')

        const [broadcast, workflow] = captured('message audience shown')
        expect(broadcast.attempt_id).not.toEqual(workflow.attempt_id)
        expect(attemptInUrl('cohort', 'broadcast')).toEqual(broadcast.attempt_id)
        expect(attemptInUrl('cohort', 'workflow')).toEqual(workflow.attempt_id)
    })

    it('starts the attempt at the click when the spot never reported it was shown', () => {
        captureMessageAudienceClicked('survey_respondents', 'broadcast')

        const [clicked] = captured('message audience clicked')
        expect(clicked.attempt_id).toEqual(expect.any(String))
        expect(attemptInUrl('survey_respondents', 'broadcast')).toEqual(clicked.attempt_id)
    })

    it('opens the editor without an attempt from a spot that was never shown or clicked', () => {
        expect(attemptInUrl('autoresearch', 'workflow')).toBeNull()
    })
})
