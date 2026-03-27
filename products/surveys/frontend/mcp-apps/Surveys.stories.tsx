import { McpThemeDecorator } from '@common/mosaic/storybook/decorator'
import type { Meta, StoryObj } from '@storybook/react'

import {
    type SurveyData,
    type SurveyListData,
    SurveyListView,
    type SurveyStatsData,
    SurveyStatsView,
    SurveyView,
} from './index'

const meta: Meta = {
    title: 'MCP Apps/Surveys',
    decorators: [McpThemeDecorator],
    parameters: {
        testOptions: {
            // McpThemeDecorator doesn't have dark mode built-in by default so just disable this to avoid duplicated snapshots
            skipDarkMode: true,
        },
    },
}
export default meta

type Story = StoryObj<{}>

const activePopover: SurveyData = {
    id: 'survey-1',
    name: 'NPS survey Q4',
    description: 'Quarterly NPS measurement for all active users.',
    type: 'popover',
    status: 'active',
    start_date: '2025-10-01T00:00:00Z',
    created_at: '2025-09-28T09:00:00Z',
    responses_limit: 1000,
    questions: [
        {
            type: 'nps',
            question: 'How likely are you to recommend PostHog to a friend or colleague?',
        },
        {
            type: 'open',
            question: 'What could we do to improve your experience?',
            description: 'Optional free-text feedback',
        },
    ],
    _posthogUrl: 'https://us.posthog.com/project/1/surveys/survey-1',
}

const draftMultiQuestion: SurveyData = {
    id: 'survey-2',
    name: 'Feature satisfaction',
    type: 'api',
    status: 'draft',
    created_at: '2025-12-01T09:00:00Z',
    questions: [
        {
            type: 'rating',
            question: 'How satisfied are you with the dashboard?',
            scale: 5,
            lowerBoundLabel: 'Very unsatisfied',
            upperBoundLabel: 'Very satisfied',
        },
        {
            type: 'single_choice',
            question: 'Which feature do you use most?',
            choices: ['Analytics', 'Feature flags', 'Session replay', 'Surveys'],
        },
        {
            type: 'multiple_choice',
            question: 'Which areas need improvement?',
            choices: ['Performance', 'Documentation', 'UI/UX', 'Integrations'],
        },
    ],
}

const completedSurvey: SurveyData = {
    id: 'survey-3',
    name: 'Beta feedback form',
    type: 'widget',
    status: 'completed',
    start_date: '2025-08-01T00:00:00Z',
    end_date: '2025-09-01T00:00:00Z',
    created_at: '2025-07-28T09:00:00Z',
    responses_limit: 500,
    questions: [
        {
            type: 'open',
            question: 'What did you think of the beta?',
        },
    ],
    _posthogUrl: 'https://us.posthog.com/project/1/surveys/survey-3',
}

export const ActivePopover: Story = {
    render: () => <SurveyView survey={activePopover} />,
    storyName: 'Active popover survey',
}

export const DraftMultiQuestion: Story = {
    render: () => <SurveyView survey={draftMultiQuestion} />,
    storyName: 'Draft with multiple question types',
}

export const Completed: Story = {
    render: () => <SurveyView survey={completedSurvey} />,
    storyName: 'Completed survey',
}

const sampleListData: SurveyListData = {
    results: [activePopover, draftMultiQuestion, completedSurvey],
    _posthogUrl: 'https://us.posthog.com/project/1/surveys',
}

export const List: Story = {
    render: () => <SurveyListView data={sampleListData} />,
    storyName: 'Survey list',
}

const sampleStats: SurveyStatsData = {
    survey_id: 'survey-1',
    stats: {
        'survey shown': { total_count: 8420, unique_persons: 6200 },
        'survey sent': { total_count: 2150, unique_persons: 2100 },
        'survey dismissed': { total_count: 1830, unique_persons: 1700 },
    },
    rates: {
        response_rate: 0.255,
        dismissal_rate: 0.217,
    },
    _posthogUrl: 'https://us.posthog.com/project/1/surveys/survey-1',
}

export const Stats: Story = {
    render: () => <SurveyStatsView data={sampleStats} />,
    storyName: 'Survey stats',
}
