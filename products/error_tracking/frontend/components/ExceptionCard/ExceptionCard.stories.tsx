import { Meta } from '@storybook/react'

import { mswDecorator } from '~/mocks/browser'
import { ErrorTrackingRelationalIssue } from '~/queries/schema/schema-general'

import { TEST_EVENTS } from '../../__mocks__/events'
import { ExceptionCard } from './ExceptionCard'

const meta: Meta = {
    title: 'ErrorTracking/ExceptionCard',
    parameters: {
        layout: 'centered',
        viewMode: 'story',
    },
    decorators: [
        mswDecorator({
            post: {
                'api/environments/:team_id/error_tracking/stack_frames/batch_get/': require('../../__mocks__/stack_frames/batch_get'),
            },
        }),
    ],
}

export default meta

////////////////////// Generic stacktraces

export function ExceptionCardBase(): JSX.Element {
    return (
        <div className="w-[800px]">
            <ExceptionCard
                issue={issue}
                issueLoading={false}
                event={TEST_EVENTS['javascript_resolved'] as any}
                eventLoading={false}
            />
        </div>
    )
}

export function ExceptionCardIssueLoading(): JSX.Element {
    return (
        <div className="w-[800px]">
            <ExceptionCard issue={issue} issueLoading={true} event={undefined} eventLoading={true} />
        </div>
    )
}
ExceptionCardIssueLoading.tags = ['test-skip']

export function ExceptionCardEventLoading(): JSX.Element {
    return (
        <div className="w-[800px]">
            <ExceptionCard issue={issue} issueLoading={false} event={undefined} eventLoading={true} />
        </div>
    )
}
ExceptionCardEventLoading.tags = ['test-skip']

//////////////////// Utils

const issue = {
    id: '123',
    name: 'Issue Title',
    description: 'Issue Description',
    status: 'active',
    assignee: null,
    first_seen: '2022-01-05',
} as ErrorTrackingRelationalIssue
