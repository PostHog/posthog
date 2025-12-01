import { Meta } from '@storybook/react'

import { ErrorEventType } from 'lib/components/Errors/types'

import { mswDecorator } from '~/mocks/browser'

import { TEST_EVENTS } from '../../__mocks__/events'
import { StyleVariables } from '../StyleVariables'
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
        (Story) => (
            <StyleVariables>
                {/* 👇 Decorators in Storybook also accept a function. Replace <Story/> with Story() to enable it  */}
                <Story />
            </StyleVariables>
        ),
    ],
}

export default meta

////////////////////// Generic stacktraces

export function ExceptionCardBase(): JSX.Element {
    return (
        <div className="w-[800px]">
            <ExceptionCard issueId="issue-id" loading={false} event={TEST_EVENTS['javascript_resolved'] as any} />
        </div>
    )
}

export function ExceptionCardNoInApp(): JSX.Element {
    return (
        <div className="w-[800px]">
            <ExceptionCard issueId="issue-id" loading={false} event={TEST_EVENTS['javascript_no_in_app'] as any} />
        </div>
    )
}

export function ExceptionCardLoading(): JSX.Element {
    return (
        <div className="w-[800px]">
            <ExceptionCard issueId="issue-id" loading={true} event={undefined} />
        </div>
    )
}
ExceptionCardLoading.tags = ['test-skip']

//////////////////// Utils

function ExceptionCardWrapperAllEvents({
    children,
}: {
    children: (issueId: string, event: Partial<ErrorEventType>) => JSX.Element
}): JSX.Element {
    return (
        <div className="space-y-8">
            {Object.entries(TEST_EVENTS).map(([name, evt]: [string, any]) => {
                return <div key={name}>{children(name, evt)}</div>
            })}
        </div>
    )
}

export function ExceptionCardAllEvents(): JSX.Element {
    return (
        <ExceptionCardWrapperAllEvents>
            {(issueId, event) => <ExceptionCard issueId={issueId} loading={false} event={event as ErrorEventType} />}
        </ExceptionCardWrapperAllEvents>
    )
}
