import { MOCK_DEFAULT_ORGANIZATION } from 'lib/api.mock'

import type { Meta, StoryObj } from '@storybook/react'
import { useActions } from 'kea'

import { FEATURE_FLAGS } from 'lib/constants'
import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { organizationLogic } from 'scenes/organizationLogic'
import { urls } from 'scenes/urls'

import { AskPostHogAi } from './AskPostHogAi'

function AskPostHogAiStory({ approved = true }: { approved?: boolean }): JSX.Element {
    const { loadCurrentOrganizationSuccess } = useActions(organizationLogic)

    useOnMountEffect(() => {
        loadCurrentOrganizationSuccess({
            ...MOCK_DEFAULT_ORGANIZATION,
            is_ai_data_processing_approved: approved,
        })
    })

    return <AskPostHogAi />
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
        const firstQuestion = Array.from(canvasElement.querySelectorAll('button')).find(
            (button) => button.textContent?.trim() === question
        )

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
        await new Promise<void>((resolve) => requestAnimationFrame(() => resolve()))
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
