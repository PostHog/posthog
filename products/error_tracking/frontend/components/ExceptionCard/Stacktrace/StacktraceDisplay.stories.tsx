import { Meta } from '@storybook/react'

import { LemonCard } from '@posthog/lemon-ui'

import { sceneLogic } from 'scenes/sceneLogic'

import { mswDecorator } from '~/mocks/browser'

import { ExceptionLogicWrapper, TEST_EVENTS, TestEventName } from '../../../__mocks__/events'
import { StacktraceBaseDisplayProps, StacktraceEmptyDisplay } from './StacktraceBase'
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
    return (
        <ExceptionLogicWrapper eventName="python_resolved" loading={true}>
            <StacktraceGenericDisplay {...DEFAULT_PROPS} />
        </ExceptionLogicWrapper>
    )
}

export function GenericDisplayEmpty(): JSX.Element {
    return (
        <ExceptionLogicWrapper eventName="javascript_empty">
            <StacktraceGenericDisplay {...DEFAULT_PROPS} />
        </ExceptionLogicWrapper>
    )
}

export function GenericDisplayWithStacktrace(): JSX.Element {
    return (
        <StacktraceWrapperAllEvents>
            <StacktraceGenericDisplay {...DEFAULT_PROPS} />
        </StacktraceWrapperAllEvents>
    )
}

export function GenericDisplayWithJavascriptScriptError(): JSX.Element {
    return (
        <ExceptionLogicWrapper eventName="javascript_script_error">
            <StacktraceGenericDisplay {...DEFAULT_PROPS} />
        </ExceptionLogicWrapper>
    )
}

///////////////////// Text stacktraces

export function TextDisplayEmpty(): JSX.Element {
    return (
        <ExceptionLogicWrapper eventName="javascript_empty">
            <StacktraceTextDisplay {...DEFAULT_PROPS} />
        </ExceptionLogicWrapper>
    )
}

export function TextDisplayPropertiesLoading(): JSX.Element {
    return (
        <ExceptionLogicWrapper eventName="javascript_resolved">
            <StacktraceTextDisplay {...DEFAULT_PROPS} />
        </ExceptionLogicWrapper>
    )
}

export function TextDisplayWithStacktrace(): JSX.Element {
    return (
        <StacktraceWrapperAllEvents>
            <StacktraceTextDisplay {...DEFAULT_PROPS} />
        </StacktraceWrapperAllEvents>
    )
}

//////////////////// Utils

const DEFAULT_PROPS = {
    truncateMessage: true,
    renderEmpty: () => <StacktraceEmptyDisplay />,
} as StacktraceBaseDisplayProps

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
