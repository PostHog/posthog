import { MOCK_DEFAULT_TEAM, MOCK_DEFAULT_USER } from 'lib/api.mock'

import type { Meta, StoryObj } from '@storybook/react'
import { useEffect } from 'react'

import { teamLogic } from 'scenes/teamLogic'
import { userLogic } from 'scenes/userLogic'

import { mswDecorator } from '~/mocks/browser'

import type { ScoutTrialLaunchApi } from 'products/signals/frontend/generated/api.schemas'

import { ScoutTrials } from './ScoutTrials'
import { trialFixtureConfig, trialFixtureResult, trialFixtureSetup } from './scoutTrialsFixtures'

const submissions = new Map<string, ScoutTrialLaunchApi>()

const meta: Meta<typeof ScoutTrials> = {
    title: 'Scenes-App/Inbox/Scout comparisons interactive',
    component: ScoutTrials,
    parameters: { layout: 'fullscreen', testOptions: { waitForLoadersToDisappear: false } },
    decorators: [
        (Story) => {
            useEffect(() => {
                teamLogic.actions.loadCurrentTeamSuccess({ ...MOCK_DEFAULT_TEAM, id: 2 })
                userLogic.actions.loadUserSuccess({ ...MOCK_DEFAULT_USER, id: 42, is_staff: true })
            }, [])
            return <Story />
        },
        mswDecorator({
            get: {
                '/api/users/@me/': () => [200, { ...MOCK_DEFAULT_USER, id: 42, is_staff: true }],
                '/api/projects/:team/signals/scout/configs/': () => [200, [trialFixtureConfig]],
                '/api/projects/:team/signals/scout/configs/:config/trial_setup/': () => [200, trialFixtureSetup],
                '/api/projects/:team/signals/scout/configs/:config/trial_history/': () => [
                    200,
                    { results: [], has_more: false },
                ],
                '/api/projects/:team/signals/scout/configs/:config/trial_result/': ({ request }) => {
                    const launchId = new URL(request.url).searchParams.get('launch_id')!
                    const submission = submissions.get(launchId)
                    return [
                        200,
                        {
                            ...trialFixtureResult,
                            launch_id: launchId,
                            model: submission?.model ?? trialFixtureResult.model,
                            reasoning_effort: submission?.reasoning_effort ?? trialFixtureResult.reasoning_effort,
                        },
                    ]
                },
            },
            post: {
                '/api/projects/:team/signals/scout/configs/:config/trial/': async ({ request }) => {
                    const payload = (await request.json()) as ScoutTrialLaunchApi
                    submissions.set(payload.launch_id, payload)
                    return [
                        202,
                        {
                            launch_id: payload.launch_id,
                            context_id: trialFixtureResult.context_id,
                            workflow_id: payload.launch_id,
                            model: payload.model,
                            reasoning_effort: payload.reasoning_effort,
                            variant: payload.variant,
                        },
                    ]
                },
                '/api/projects/:team/tasks/:task/runs/:run/cancel/': () => [200, {}],
            },
        }),
    ],
}
export default meta
type Story = StoryObj<typeof ScoutTrials>

export const Interactive: Story = {}
export const Running: Story = {
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team/signals/scout/configs/:config/trial_result/': ({ request }) => [
                    200,
                    {
                        ...trialFixtureResult,
                        launch_id: new URL(request.url).searchParams.get('launch_id'),
                        status: 'running',
                        task_status: 'running',
                        reports: [],
                        memory: {},
                        summary: '',
                        completed_at: null,
                    },
                ],
            },
        }),
    ],
}
