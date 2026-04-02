import type { Meta, StoryObj } from '@storybook/react'
import { router } from 'kea-router'

import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { urls } from 'scenes/urls'

import { useStorybookMocks } from '~/mocks/browser'
import { LLMTrace } from '~/queries/schema/schema-general'

import fullTrace from './__mocks__/fullTrace.json'
import traceWithoutContent from './__mocks__/traceWithoutContent.json'
import { LLMAnalyticsTraceScene } from './LLMAnalyticsTraceScene'

interface LLMAnalyticsTraceSceneProps {
    trace: LLMTrace
    eventId?: string
}

const meta: Meta<LLMAnalyticsTraceSceneProps> = {
    title: 'Scenes-App/LLM Analytics/Trace',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2023-01-28', // To stabilize relative dates
    },
    render: ({ trace, eventId }) => {
        useStorybookMocks({
            post: {
                '/api/environments/:team_id/query/': () => [200, { results: [trace] }],
            },
        })

        useOnMountEffect(() => {
            router.actions.push(
                urls.llmAnalyticsTrace(trace.id, eventId ? { event: eventId, timestamp: trace.createdAt } : undefined)
            )
        })

        return (
            <div className="relative flex flex-col p-4">
                <LLMAnalyticsTraceScene />
            </div>
        )
    },
}
export default meta
type Story = StoryObj<LLMAnalyticsTraceSceneProps>

export const Full: Story = {
    args: {
        trace: fullTrace,
    },
}

export const FullSpecificEvent: Story = {
    args: {
        trace: fullTrace,
        eventId: fullTrace.events.at(-8)!.id,
    },
}

export const WithoutContent: Story = {
    args: {
        trace: traceWithoutContent,
    },
}
