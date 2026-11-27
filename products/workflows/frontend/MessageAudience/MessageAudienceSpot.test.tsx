import '@testing-library/jest-dom'

import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { router } from 'kea-router'
import posthog from 'posthog-js'
import { mockAllIsIntersecting, mockIsIntersecting } from 'react-intersection-observer/test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { AccessControlLevel, AccessControlResourceType, PropertyFilterType, PropertyOperator } from '~/types'

import { MessageAudience, captureMessageAudienceClicked } from './messageAudience'
import { MessageAudienceButton } from './MessageAudienceButton'
import { MessageAudienceSpot } from './MessageAudienceSpot'

const audience: MessageAudience = {
    source: 'early_access_feature',
    properties: [{ key: 'id', type: PropertyFilterType.Cohort, value: 7, operator: PropertyOperator.In }],
}

describe('message audience on-screen events', () => {
    let captured: { event: string; properties: Record<string, any> }[]

    const events = (name: string): Record<string, any>[] =>
        captured.filter((capture) => capture.event === name).map((capture) => capture.properties)

    const clickAndOpen = async (label: string): Promise<void> => {
        const startedOn = router.values.location.pathname
        fireEvent.click(screen.getByText(label))
        await waitFor(() => expect(router.values.location.pathname).not.toEqual(startedOn))
    }

    beforeEach(() => {
        useMocks({
            get: {
                '/api/projects/:team_id/hog_flows/email_sending_suspension/': { email_sending_suspended: false },
                '/api/projects/:team_id/integrations/': {
                    results: [{ id: 1, kind: 'email', config: { verified: true } }],
                    next: null,
                },
                '/api/projects/:team_id/cohorts/:id/': {
                    id: 7,
                    name: 'Beta testers',
                    is_static: false,
                    is_calculating: false,
                    last_calculation: '2026-11-01T00:00:00Z',
                    count: 3,
                },
            },
        })
        initKeaTests()
        router.actions.push('/project/997/early_access_features/1')
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

    it('reports a button once it is on screen, and its click carries the same attempt', async () => {
        render(<MessageAudienceButton audience={audience} destinations={['broadcast']} label="Email them" />)
        expect(events('message audience shown')).toEqual([])

        act(() => mockAllIsIntersecting(true))
        act(() => mockAllIsIntersecting(false))
        act(() => mockAllIsIntersecting(true))
        const shown = events('message audience shown')
        expect(shown).toEqual([
            { source: 'early_access_feature', destination: 'broadcast', attempt_id: expect.any(String) },
        ])

        await clickAndOpen('Email them')
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

    it('keeps the attempt of a button that stays when another one for the same audience goes away', async () => {
        render(<MessageAudienceButton audience={audience} destinations={['broadcast']} label="In the panel" />)
        act(() => mockAllIsIntersecting(true))
        const menu = render(
            <MessageAudienceButton audience={audience} destinations={['broadcast']} label="In the menu" />
        )
        act(() => mockAllIsIntersecting(true))
        menu.unmount()

        await clickAndOpen('In the panel')
        const [panelShown] = events('message audience shown')
        expect(events('message audience clicked')).toEqual([
            { source: 'early_access_feature', destination: 'broadcast', attempt_id: panelShown.attempt_id },
        ])
    })

    it('reports nothing for a button the person cannot use', () => {
        render(
            <MessageAudienceButton
                audience={audience}
                destinations={['broadcast']}
                label="Email them"
                disabledReason="You need editor access to workflows"
            />
        )
        act(() => mockAllIsIntersecting(true))

        expect(events('message audience shown')).toEqual([])
    })

    it('reports a button that was disabled only once it is on screen while usable', () => {
        const spot = (disabled: boolean): JSX.Element => (
            <MessageAudienceSpot source="cohort" destination="broadcast" disabled={disabled}>
                Email this cohort
            </MessageAudienceSpot>
        )
        const { rerender } = render(spot(true))
        act(() => mockAllIsIntersecting(true))
        act(() => mockAllIsIntersecting(false))
        rerender(spot(false))
        expect(events('message audience shown')).toEqual([])

        act(() => mockAllIsIntersecting(true))
        expect(events('message audience shown')).toEqual([
            { source: 'cohort', destination: 'broadcast', attempt_id: expect.any(String) },
        ])
    })

    it('reports a button again when it switches to another destination', async () => {
        const { rerender } = render(
            <MessageAudienceButton audience={audience} destinations={['broadcast']} label="Email them" />
        )
        act(() => mockAllIsIntersecting(true))
        rerender(<MessageAudienceButton audience={audience} destinations={['workflow']} label="Email them" />)
        act(() => mockAllIsIntersecting(true))

        const shown = events('message audience shown')
        expect(shown.map(({ destination }) => destination)).toEqual(['broadcast', 'workflow'])
        await clickAndOpen('Email them')
        expect(events('message audience clicked')).toEqual([
            { source: 'early_access_feature', destination: 'workflow', attempt_id: shown[1].attempt_id },
        ])
    })

    it('reports a label that comes on screen and leaves again before the page updates', () => {
        render(<MessageAudienceButton audience={audience} destinations={['broadcast']} label="Email them" />)
        act(() => {
            mockAllIsIntersecting(true)
            mockAllIsIntersecting(false)
        })

        expect(events('message audience shown')).toEqual([
            { source: 'early_access_feature', destination: 'broadcast', attempt_id: expect.any(String) },
        ])
    })

    it('gives a click the attempt of the button that was seen, not one enabled offscreen', async () => {
        const below = (disabledReason?: string): JSX.Element => (
            <MessageAudienceButton
                audience={audience}
                destinations={['broadcast']}
                label="Below the fold"
                disabledReason={disabledReason}
            />
        )
        const offscreen = render(below('Checking access'))
        render(<MessageAudienceButton audience={audience} destinations={['broadcast']} label="On screen" />)
        act(() => mockIsIntersecting(screen.getByText('On screen'), true))
        offscreen.rerender(below())

        await clickAndOpen('On screen')
        const shown = events('message audience shown')
        expect(shown).toHaveLength(1)
        expect(events('message audience clicked')).toEqual([
            { source: 'early_access_feature', destination: 'broadcast', attempt_id: shown[0].attempt_id },
        ])
    })

    it('gives a click its own attempt when another button for the audience switches destination', async () => {
        render(<MessageAudienceButton audience={audience} destinations={['broadcast']} label="First" />)
        act(() => mockAllIsIntersecting(true))
        const second = render(<MessageAudienceButton audience={audience} destinations={['broadcast']} label="Second" />)
        act(() => mockAllIsIntersecting(true))
        second.rerender(<MessageAudienceButton audience={audience} destinations={['workflow']} label="Second" />)
        act(() => mockAllIsIntersecting(true))

        await clickAndOpen('First')
        const [firstShown] = events('message audience shown')
        expect(events('message audience clicked')).toEqual([
            { source: 'early_access_feature', destination: 'broadcast', attempt_id: firstShown.attempt_id },
        ])
    })

    it('keeps one attempt per destination when a button switches away and back', () => {
        const button = (destination: 'broadcast' | 'workflow'): JSX.Element => (
            <MessageAudienceButton audience={audience} destinations={[destination]} label="Email them" />
        )
        const { rerender } = render(button('broadcast'))
        act(() => mockAllIsIntersecting(true))
        rerender(button('workflow'))
        act(() => mockAllIsIntersecting(true))
        rerender(button('broadcast'))
        act(() => mockAllIsIntersecting(true))

        expect(events('message audience shown').map(({ destination }) => destination)).toEqual([
            'broadcast',
            'workflow',
        ])
    })

    it('reports each menu destination only once the menu opens', async () => {
        render(<MessageAudienceButton audience={audience} label="Email them" />)
        act(() => mockAllIsIntersecting(true))
        expect(events('message audience shown')).toEqual([])

        fireEvent.click(screen.getByText('Email them'))
        act(() => mockAllIsIntersecting(true))
        const shown = events('message audience shown')
        expect(shown.map(({ destination }) => destination).sort()).toEqual(['broadcast', 'workflow'])

        await clickAndOpen('Build a custom workflow')
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
