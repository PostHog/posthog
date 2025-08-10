import { LemonCard } from '@posthog/lemon-ui'
import { Meta } from '@storybook/react'
import { sceneLogic } from 'scenes/sceneLogic'

import { mswDecorator } from '~/mocks/browser'
import { ErrorTrackingRelationalIssue } from '~/queries/schema/schema-general'

import { ExceptionLogicWrapper, TEST_EVENTS, TestEventName } from '../../../__mocks__/events'
import { HeaderRenderer, StacktraceBaseDisplayProps, StacktraceEmptyDisplay } from './StacktraceBase'
import { StacktraceGenericDisplay } from './StacktraceGenericDisplay'
import { StacktraceTextDisplay } from './StacktraceTextDisplay'

const meta: Meta = {
    title: 'ErrorTracking/StacktraceDisplay',
    parameters: {
        layout: 'centered',
        viewMode: 'story',
    },
    decorators: [
        (Story: React.FC): JSX.Element => {
            sceneLogic.mount()
            return (
                <LemonCard hoverEffect={false} className="p-2 px-3 w-[900px]">
                    <Story />
                </LemonCard>
            )
        },
        mswDecorator({
            post: {
                'api/environments/:team_id/error_tracking/stack_frames/batch_get/': require('../../../__mocks__/stack_frames/batch_get'),
            },
        }),
    ],
}

export default meta

////////////////////// Generic stacktraces

export function GenericDisplayPropertiesLoading(): JSX.Element {
    const props = defaultBaseProps({}, false)
    return (
        <ExceptionLogicWrapper eventName="python_resolved" loading={true}>
            <StacktraceGenericDisplay {...props} />
        </ExceptionLogicWrapper>
    )
}

export function GenericDisplayEmpty(): JSX.Element {
    const props = defaultBaseProps({}, false)
    return (
        <ExceptionLogicWrapper eventName="javascript_empty">
            <StacktraceGenericDisplay {...props} />
        </ExceptionLogicWrapper>
    )
}

export function GenericDisplayWithStacktrace(): JSX.Element {
    const props = defaultBaseProps({}, false)
    return (
        <StacktraceWrapperAllEvents>
            <StacktraceGenericDisplay {...props} />
        </StacktraceWrapperAllEvents>
    )
}

///////////////////// Text stacktraces

export function TextDisplayEmpty(): JSX.Element {
    const props = defaultBaseProps({}, false)
    return (
        <ExceptionLogicWrapper eventName="javascript_empty">
            <StacktraceTextDisplay {...props} />
        </ExceptionLogicWrapper>
    )
}

export function TextDisplayPropertiesLoading(): JSX.Element {
    const props = defaultBaseProps({}, false)
    return (
        <ExceptionLogicWrapper eventName="javascript_resolved">
            <StacktraceTextDisplay {...props} />
        </ExceptionLogicWrapper>
    )
}

export function TextDisplayWithStacktrace(): JSX.Element {
    const props = defaultBaseProps({}, false)
    return (
        <StacktraceWrapperAllEvents>
            <StacktraceTextDisplay {...props} />
        </StacktraceWrapperAllEvents>
    )
}

//////////////////// Utils

const issue = {
    id: '123',
    name: 'Issue Title',
    description: 'Issue Description',
    status: 'active',
    assignee: null,
    first_seen: '2022-01-05',
} as ErrorTrackingRelationalIssue

function defaultBaseProps(
    overrideProps: Partial<StacktraceBaseDisplayProps> = {},
    issueLoading: boolean = false
): StacktraceBaseDisplayProps {
    return {
        truncateMessage: true,
        renderLoading: (renderHeader: HeaderRenderer) =>
            renderHeader({
                type: issue?.name ?? undefined,
                value: issue?.description ?? undefined,
                loading: issueLoading,
            }),
        renderEmpty: () => <StacktraceEmptyDisplay />,
        ...overrideProps,
    } as StacktraceBaseDisplayProps
}

function StacktraceWrapperAllEvents({ children }: { children: JSX.Element }): JSX.Element {
    const eventNames = Object.keys(TEST_EVENTS) as TestEventName[]
    return (
        <div className="space-y-4">
            {eventNames.map((name: TestEventName) => {
                return (
                    <ExceptionLogicWrapper key={name} eventName={name}>
                        <LemonCard hoverEffect={false} className="px-3 py-2">
                            {children}
                        </LemonCard>
                    </ExceptionLogicWrapper>
                )
            })}
        </div>
    )
}
