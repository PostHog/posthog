import '@testing-library/jest-dom'

import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import posthog from 'posthog-js'
import { mockAllIsIntersecting } from 'react-intersection-observer/test-utils'

import { initKeaTests } from '~/test/init'
import { AccessControlLevel, AccessControlResourceType, PropertyFilterType, PropertyOperator } from '~/types'

import { MessageAudience, captureMessageAudienceClicked } from './messageAudience'
import { MessageAudienceButton } from './MessageAudienceButton'

jest.mock('./messageAudienceWarnings', () => ({ openMessageAudience: jest.fn(async () => {}) }))

const audience: MessageAudience = {
    source: 'early_access_feature',
    properties: [{ key: 'id', type: PropertyFilterType.Cohort, value: 7, operator: PropertyOperator.In }],
}

describe('message audience on-screen events', () => {
    let captured: { event: string; properties: Record<string, any> }[]

    const events = (name: string): Record<string, any>[] =>
        captured.filter((capture) => capture.event === name).map((capture) => capture.properties)

    beforeEach(() => {
        initKeaTests()
        window.POSTHOG_APP_CONTEXT = {
            ...window.POSTHOG_APP_CONTEXT!,
            resource_access_control: {
                ...window.POSTHOG_APP_CONTEXT!.resource_access_control,
                [AccessControlResourceType.Workflow]: AccessControlLevel.Editor,
            },
        }
        captured = []
        jest.spyOn(posthog, 'capture').mockImplementation((event, properties) => {
            captured.push({ event, properties: properties ?? {} })
            return undefined
        })
    })

    afterEach(() => {
        cleanup()
        jest.restoreAllMocks()
    })

    it('reports a button once it is on screen, and its click carries the same attempt', () => {
        render(<MessageAudienceButton audience={audience} destinations={['broadcast']} label="Email them" />)
        expect(events('message audience shown')).toEqual([])

        act(() => mockAllIsIntersecting(true))
        act(() => mockAllIsIntersecting(false))
        act(() => mockAllIsIntersecting(true))
        const shown = events('message audience shown')
        expect(shown).toEqual([
            { source: 'early_access_feature', destination: 'broadcast', attempt_id: expect.any(String) },
        ])

        fireEvent.click(screen.getByText('Email them'))
        expect(events('message audience clicked')).toEqual([
            { source: 'early_access_feature', destination: 'broadcast', attempt_id: shown[0].attempt_id },
        ])
    })

    it('starts a new attempt each time the button mounts', () => {
        const first = render(<MessageAudienceButton audience={audience} destinations={['broadcast']} />)
        act(() => mockAllIsIntersecting(true))
        first.unmount()
        render(<MessageAudienceButton audience={audience} destinations={['broadcast']} />)
        act(() => mockAllIsIntersecting(true))

        const [firstShown, secondShown] = events('message audience shown')
        expect(secondShown.attempt_id).not.toEqual(firstShown.attempt_id)
    })

    it('reports each menu destination only once the menu opens', () => {
        render(<MessageAudienceButton audience={audience} label="Email them" />)
        act(() => mockAllIsIntersecting(true))
        expect(events('message audience shown')).toEqual([])

        fireEvent.click(screen.getByText('Email them'))
        act(() => mockAllIsIntersecting(true))
        const shown = events('message audience shown')
        expect(shown.map(({ destination }) => destination).sort()).toEqual(['broadcast', 'workflow'])

        fireEvent.click(screen.getByText('Build a custom workflow'))
        expect(events('message audience clicked')).toEqual([
            {
                source: 'early_access_feature',
                destination: 'workflow',
                attempt_id: shown.find(({ destination }) => destination === 'workflow')?.attempt_id,
            },
        ])
    })

    it('gives a click with nothing on screen an attempt of its own', () => {
        captureMessageAudienceClicked('cohort', 'broadcast')
        captureMessageAudienceClicked('cohort', 'broadcast')

        const [first, second] = events('message audience clicked')
        expect(first.attempt_id).toEqual(expect.any(String))
        expect(second.attempt_id).not.toEqual(first.attempt_id)
    })
})
