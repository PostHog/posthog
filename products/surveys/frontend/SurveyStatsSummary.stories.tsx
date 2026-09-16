import { Meta, StoryObj } from '@storybook/react'
import { BindLogic } from 'kea'

import { surveyLogic } from 'scenes/surveys/surveyLogic'
import { SurveyStatsSummaryWithData } from 'scenes/surveys/SurveyStatsSummary'
import { getSurveyResponseOutcomeBreakdown } from 'scenes/surveys/utils'

import { SurveyEventName, SurveyStats } from '~/types'

const stats: SurveyStats = {
    [SurveyEventName.SHOWN]: {
        total_count: 24000,
        unique_persons: 20000,
        total_count_only_seen: 7200,
        unique_persons_only_seen: 6000,
        first_seen: null,
        last_seen: null,
    },
    [SurveyEventName.SENT]: {
        total_count: 960,
        unique_persons: 800,
        total_count_only_seen: 0,
        unique_persons_only_seen: 0,
        first_seen: null,
        last_seen: null,
    },
    [SurveyEventName.DISMISSED]: {
        total_count: 15840,
        unique_persons: 13200,
        total_count_only_seen: 0,
        unique_persons_only_seen: 0,
        first_seen: null,
        last_seen: null,
    },
}

const meta: Meta<typeof SurveyStatsSummaryWithData> = {
    title: 'Surveys/Survey performance',
    component: SurveyStatsSummaryWithData,
    decorators: [
        (Story, { parameters }) => (
            <div style={{ width: parameters.width ?? 960 }}>
                <BindLogic logic={surveyLogic} props={{ id: 'new' }}>
                    <Story />
                </BindLogic>
            </div>
        ),
    ],
    args: {
        outcomes: getSurveyResponseOutcomeBreakdown([504, 432, 24]),
        processedSurveyStats: stats,
        surveyRates: {
            response_rate: 4,
            unique_users_response_rate: 4,
            dismissal_rate: 66,
            unique_users_dismissal_rate: 66,
        },
    },
}
export default meta

type Story = StoryObj<typeof meta>

export const Default: Story = {}

export const Narrow: Story = { parameters: { width: 512 } }

export const Loading: Story = {
    args: { isLoading: true },
    parameters: { testOptions: { waitForLoadersToDisappear: false } },
}

export const NoResponses: Story = {
    args: {
        outcomes: getSurveyResponseOutcomeBreakdown([0, 0, 0]),
        processedSurveyStats: {
            ...stats,
            [SurveyEventName.SENT]: { ...stats[SurveyEventName.SENT], total_count: 0, unique_persons: 0 },
            [SurveyEventName.SHOWN]: {
                ...stats[SurveyEventName.SHOWN],
                total_count_only_seen: 8160,
                unique_persons_only_seen: 6800,
            },
        },
        surveyRates: { ...meta.args!.surveyRates!, response_rate: 0, unique_users_response_rate: 0 },
    },
}
