import { MOCK_DEFAULT_ORGANIZATION } from 'lib/api.mock'

import type { Meta, StoryObj } from '@storybook/react'
import { useActions } from 'kea'
import { useState } from 'react'

import { FEATURE_FLAGS } from 'lib/constants'
import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { organizationLogic } from 'scenes/organizationLogic'
import { urls } from 'scenes/urls'
import { defaultConversionGoalFilter } from 'scenes/web-analytics/tabs/marketing-analytics/frontend/components/settings/constants'
import { marketingAnalyticsLogic } from 'scenes/web-analytics/tabs/marketing-analytics/frontend/logic/marketingAnalyticsLogic'

import { sidePanelStateLogic } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'
import { PropertyFilterType, PropertyOperator, SidePanelTab } from '~/types'

import { AskPostHogAi } from './AskPostHogAi'

function AskPostHogAiStory({ approved = true }: { approved?: boolean }): JSX.Element {
    const [ready, setReady] = useState(false)
    const { loadCurrentOrganizationSuccess } = useActions(organizationLogic)
    const { setDashboardProperties, setDates, setDraftConversionGoal } = useActions(marketingAnalyticsLogic)

    useOnMountEffect(() => {
        loadCurrentOrganizationSuccess({
            ...MOCK_DEFAULT_ORGANIZATION,
            is_ai_data_processing_approved: approved,
        })
        setDates('-30d', '2026-09-24')
        setDraftConversionGoal({
            ...defaultConversionGoalFilter,
            conversion_goal_id: 'storybook-purchase',
            conversion_goal_name: 'Purchase',
        })
        setDashboardProperties([
            {
                type: PropertyFilterType.Session,
                key: '$channel_type',
                operator: PropertyOperator.Exact,
                value: 'URL-controlled filter value',
            },
        ])
        setReady(true)
    })

    return ready ? <AskPostHogAi /> : <></>
}

const meta: Meta<typeof AskPostHogAi> = {
    title: 'Marketing Analytics/Dashboard/Ask PostHog AI',
    component: AskPostHogAi,
    tags: ['marketing-ask-ai'],
    render: () => <AskPostHogAiStory />,
    parameters: {
        featureFlags: [FEATURE_FLAGS.MARKETING_ANALYTICS_NEW_DASHBOARD],
        pageUrl: `${urls.marketingAnalyticsApp()}?view=overview`,
    },
}
export default meta
type Story = StoryObj<typeof meta>

export const Overview: Story = {
    play: async ({ canvasElement }) => {
        const question = 'Which channels contributed most to growth?'
        let firstQuestion: HTMLButtonElement | undefined

        for (let frame = 0; frame < 120 && !firstQuestion; frame++) {
            firstQuestion = Array.from(canvasElement.querySelectorAll('button')).find(
                (button) => button.textContent?.trim() === question
            )
            if (!firstQuestion) {
                await new Promise<void>((resolve) => requestAnimationFrame(() => resolve()))
            }
        }

        if (!firstQuestion) {
            throw new Error(`Could not find the question: ${question}`)
        }

        for (let frame = 0; frame < 120 && firstQuestion.getAttribute('aria-disabled') === 'true'; frame++) {
            await new Promise<void>((resolve) => requestAnimationFrame(() => resolve()))
        }

        if (firstQuestion.getAttribute('aria-disabled') === 'true') {
            throw new Error('The question is disabled')
        }

        firstQuestion.click()

        const expectedPrompt =
            '!Which channels contributed most to growth?\n\n' +
            'Use this Marketing Analytics dashboard context:\n' +
            'Dashboard section: overview\n' +
            'Date range: -30d to 2026-09-24\n' +
            'Breakdown: channel\n' +
            'Conversion goal: Purchase'

        for (
            let frame = 0;
            frame < 120 &&
            (sidePanelStateLogic.values.selectedTab !== SidePanelTab.Max ||
                !sidePanelStateLogic.values.sidePanelOpen ||
                sidePanelStateLogic.values.selectedTabOptions !== expectedPrompt);
            frame++
        ) {
            await new Promise<void>((resolve) => requestAnimationFrame(() => resolve()))
        }

        if (
            sidePanelStateLogic.values.selectedTab !== SidePanelTab.Max ||
            !sidePanelStateLogic.values.sidePanelOpen ||
            sidePanelStateLogic.values.selectedTabOptions !== expectedPrompt
        ) {
            throw new Error('PostHog AI did not receive the question with the dashboard context')
        }
    },
}

export const Acquisition: Story = {
    parameters: { pageUrl: `${urls.marketingAnalyticsApp()}?view=acquisition` },
}

export const Engagement: Story = {
    parameters: { pageUrl: `${urls.marketingAnalyticsApp()}?view=engagement` },
}

export const Retention: Story = {
    parameters: { pageUrl: `${urls.marketingAnalyticsApp()}?view=retention` },
}

export const Conversion: Story = {
    parameters: { pageUrl: `${urls.marketingAnalyticsApp()}?view=conversion` },
}

export const AiDataProcessingNotApproved: Story = {
    render: () => <AskPostHogAiStory approved={false} />,
}

export const Narrow: Story = {
    render: () => (
        <div className="w-[32.5rem] max-w-full">
            <AskPostHogAiStory />
        </div>
    ),
}
