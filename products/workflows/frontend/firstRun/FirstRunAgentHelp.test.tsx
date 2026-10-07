import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import posthog from 'posthog-js'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import type { HogFlowTemplateApi } from '../generated/api.schemas'
import { FirstRunAgentHelp } from './FirstRunAgentHelp'

const WELCOME: Partial<HogFlowTemplateApi> = {
    id: '019b6f44-f9a3-0000-c4a7-b8050d25d690',
    name: 'Welcome',
    scope: 'global',
    starts_on: { kind: 'event', events: ['user signed up'], detail: '' },
    tags: [],
    actions: [],
}

describe('FirstRunAgentHelp', () => {
    let seenEvents: string[]

    beforeEach(() => {
        seenEvents = []
        useMocks({
            get: {
                '/api/projects/:team_id/hog_flow_templates/': { count: 1, results: [WELCOME] },
                '/api/projects/:team_id/event_definitions/': () => [
                    200,
                    {
                        count: seenEvents.length,
                        results: seenEvents.map((name) => ({ id: name, name, last_seen_at: '2026-10-01T00:00:00Z' })),
                    },
                ],
                '/api/projects/:team_id/property_definitions/': { count: 0, results: [] },
            },
        })
        initKeaTests()
        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.WORKFLOWS_FIRST_RUN]: true })
    })

    afterEach(() => {
        cleanup()
        jest.restoreAllMocks()
        window.localStorage.clear()
    })

    function renderForProject(project: { seenEvents: string[] }): void {
        seenEvents = project.seenEvents
        render(<FirstRunAgentHelp />)
    }

    it.each([
        {
            project: 'without a signup event',
            seenEvents: [],
            missing: 'signup_event',
            asks: 'Capture an event named exactly "user signed up"',
        },
        {
            project: 'without an email property',
            seenEvents: ['user signed up'],
            missing: 'email',
            asks: 'Make sure PostHog knows the email address of each user',
        },
    ])('copies the prompt for a project $project', async ({ seenEvents, missing, asks }) => {
        const capture = jest.spyOn(posthog, 'capture').mockImplementation()
        renderForProject({ seenEvents })
        const writeText = jest.fn().mockResolvedValue(undefined)
        Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true })

        fireEvent.click(await screen.findByText('Copy prompt for your coding agent'))

        await waitFor(() => expect(writeText).toHaveBeenCalledWith(expect.stringContaining(asks)))
        expect(capture).toHaveBeenCalledWith('workflows first run agent prompt copied', { missing })
    })

    it('shows the setup agent command when asked to let the Wizard do it', async () => {
        renderForProject({ seenEvents: [] })

        fireEvent.click(await screen.findByText('Let the Wizard do it'))

        expect(screen.getByText('npx -y @posthog/wizard@latest')).toBeInTheDocument()
    })
})
