import { Meta, StoryObj } from '@storybook/react'
import { useMountedLogic, useValues } from 'kea'
import { useEffect } from 'react'

import { FEATURE_FLAGS } from 'lib/constants'
import { lemonBannerLogic } from 'lib/lemon-ui/LemonBanner/lemonBannerLogic'
import { teamLogic } from 'scenes/teamLogic'
import { userLogic } from 'scenes/userLogic'

import { mswDecorator } from '~/mocks/browser'

import { ConversionGoalNoticeState, conversionGoalDraftLogic } from './conversionGoalDraftLogic'
import { ConversionGoalRecommendationsBanner } from './ConversionGoalRecommendationsBanner'

function NoticeStory({ state }: { state: ConversionGoalNoticeState }): JSX.Element {
    const { currentTeamId } = useValues(teamLogic)
    const { user } = useValues(userLogic)
    const logic = useMountedLogic(conversionGoalDraftLogic({ projectId: currentTeamId ?? -1 }))
    const bannerLogic = useMountedLogic(
        lemonBannerLogic({ dismissKey: `marketing-conversion-setup:${user?.uuid}:${currentTeamId}` })
    )
    useEffect(() => {
        bannerLogic.actions.resetDismissKey()
        if (state === 'preview' || state === 'save' || state === 'verify') {
            logic.actions.setBusy(state)
        } else if (state === 'error') {
            logic.actions.setError('Could not preview this draft. Try again in setup.')
        } else if (state === 'saved') {
            logic.actions.setSaveStatus('saved')
        } else if (state === 'review') {
            logic.actions.receiveDraft({
                goal: {
                    kind: 'EventsNode',
                    event: 'trial_started',
                    conversion_goal_id: '__preview__',
                    conversion_goal_name: 'Trial started',
                    schema_map: {},
                    math: 'total',
                },
                date_from: '-14d',
                date_to: 'now',
            })
        }
    }, [logic, bannerLogic, state])
    return <ConversionGoalRecommendationsBanner />
}

const meta: Meta<typeof NoticeStory> = {
    title: 'Scenes-App/Marketing Analytics/Conversion goal notice',
    component: NoticeStory,
    render: (args) => (
        <div className="w-240 max-w-full">
            <NoticeStory {...args} />
        </div>
    ),
    parameters: {
        layout: 'padded',
        featureFlags: [
            FEATURE_FLAGS.PHAI_SANDBOX_MODE,
            FEATURE_FLAGS.PHAI_SCENE_AUTO_OPEN,
            FEATURE_FLAGS.MARKETING_ANALYTICS_CONVERSION_SETUP_AI,
        ],
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/marketing_analytics/conversion_recommendations/': {
                    latest_run: null,
                    result_run: null,
                    results: { recommendations: [], limitations: [] },
                    can_generate: false,
                },
                '/api/projects/:team_id/marketing_analytics/setup_plan/': { suggestions: [] },
            },
        }),
    ],
    args: { state: 'idle' },
}
export default meta
type Story = StoryObj<typeof NoticeStory>

export const FirstVisit: Story = {}
export const Previewing: Story = {
    args: { state: 'preview' },
    parameters: { testOptions: { waitForLoadersToDisappear: false } },
}
export const Review: Story = { args: { state: 'review' } }
export const Failed: Story = { args: { state: 'error' } }
export const Saving: Story = {
    args: { state: 'save' },
    parameters: { testOptions: { waitForLoadersToDisappear: false } },
}
export const Verifying: Story = {
    args: { state: 'verify' },
    parameters: { testOptions: { waitForLoadersToDisappear: false } },
}
export const Saved: Story = { args: { state: 'saved' } }
export const Narrow: Story = {
    args: { state: 'error' },
    decorators: [
        (Story) => (
            <div className="w-[520px] max-w-full">
                <Story />
            </div>
        ),
    ],
}
