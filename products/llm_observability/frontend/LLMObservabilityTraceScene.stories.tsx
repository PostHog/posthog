import { Meta, StoryFn } from '@storybook/react'
import { router } from 'kea-router'
import { useEffect } from 'react'
import { urls } from 'scenes/urls'

import { useStorybookMocks } from '~/mocks/browser'
import { LLMTrace } from '~/queries/schema'

import fullTrace from './__mocks__/fullTrace.json'
import { LLMObservabilityTraceScene } from './LLMObservabilityTraceScene'

const meta: Meta = {
    title: 'Scenes-App/LLM Observability/Trace',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2023-01-28', // To stabilize relative dates
    },
}
export default meta

const Template: StoryFn<{ trace: LLMTrace; eventId?: string }> = ({ trace, eventId }) => {
    useStorybookMocks({
        post: {
            '/api/environments/:team_id/query/': () => [200, { results: [trace] }],
        },
    })

    useEffect(() => {
        router.actions.push(
            urls.llmObservabilityTrace(trace.id, eventId ? { event: eventId, timestamp: trace.createdAt } : undefined)
        )
    }, [])

    return (
        <div
            className="relative flex flex-col p-4"
            // eslint-disable-next-line react/forbid-dom-props
            style={
                {
                    '--breadcrumbs-height-full': '0px',
                    '--scene-padding': '1rem',
                    '--scene-padding-bottom': '1rem',
                } as React.CSSProperties
            }
        >
            <LLMObservabilityTraceScene />
        </div>
    )
}

export const Full = Template.bind({})
Full.args = {
    trace: fullTrace,
}

export const FullSpecificEvent = Template.bind({})
FullSpecificEvent.args = {
    trace: fullTrace,
    eventId: fullTrace.events.at(-8)!.id,
}
