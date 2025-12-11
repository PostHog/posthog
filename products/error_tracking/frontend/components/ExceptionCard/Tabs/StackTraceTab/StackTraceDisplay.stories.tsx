import { Meta } from '@storybook/react'
import { useActions, useValues } from 'kea'

import { LemonCard } from '@posthog/lemon-ui'

import { CollapsibleExceptionList } from 'lib/components/Errors/ExceptionList/CollapsibleExceptionList'
import { RawExceptionList } from 'lib/components/Errors/ExceptionList/RawExceptionList'
import { sceneLogic } from 'scenes/sceneLogic'

import { mswDecorator } from '~/mocks/browser'

import { ExceptionLogicWrapper, TEST_EVENTS, TestEventName } from '../../../../__mocks__/events'
import { StyleVariables } from '../../../StyleVariables'
import { exceptionCardLogic } from '../../exceptionCardLogic'

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
                <StyleVariables>
                    <LemonCard hoverEffect={false} className="p-2 w-[900px]">
                        <Story />
                    </LemonCard>
                </StyleVariables>
            )
        },
        mswDecorator({
            post: {
                'api/environments/:team_id/error_tracking/stack_frames/batch_get/': require('../../../../__mocks__/stack_frames/batch_get'),
            },
        }),
    ],
}

export default meta

////////////////////// Generic stacktraces

export function GenericDisplayPropertiesLoading(): JSX.Element {
    return (
        <ExceptionLogicWrapper eventName="python_resolved" loading={true}>
            <StackTraceGenericDisplay />
        </ExceptionLogicWrapper>
    )
}
GenericDisplayPropertiesLoading.parameters = { testOptions: { waitForLoadersToDisappear: false } }

export function GenericDisplayEmpty(): JSX.Element {
    return (
        <ExceptionLogicWrapper eventName="javascript_empty">
            <StackTraceGenericDisplay />
        </ExceptionLogicWrapper>
    )
}

export function GenericDisplayWithStacktrace(): JSX.Element {
    return (
        <StacktraceWrapperAllEvents>
            <StackTraceGenericDisplay />
        </StacktraceWrapperAllEvents>
    )
}

export function GenericDisplayWithJavascriptScriptError(): JSX.Element {
    return (
        <ExceptionLogicWrapper eventName="javascript_script_error">
            <StackTraceGenericDisplay />
        </ExceptionLogicWrapper>
    )
}

export function GenericDisplayWithMinifiedReactError(): JSX.Element {
    return (
        <ExceptionLogicWrapper eventName="javascript_minified_react_error">
            <StackTraceGenericDisplay />
        </ExceptionLogicWrapper>
    )
}

export function GenericDisplayWithNonErrorPromiseRejection(): JSX.Element {
    return (
        <ExceptionLogicWrapper eventName="javascript_non_error_promise_rejection">
            <StackTraceGenericDisplay />
        </ExceptionLogicWrapper>
    )
}

export function GenericDisplayWithLongFrames(): JSX.Element {
    return (
        <ExceptionLogicWrapper eventName="node_long_frame" showAllFrames={true}>
            <StackTraceGenericDisplay />
        </ExceptionLogicWrapper>
    )
}

///////////////////// Text stacktraces

export function TextDisplayEmpty(): JSX.Element {
    return (
        <ExceptionLogicWrapper eventName="javascript_empty">
            <StackTraceRawDisplay />
        </ExceptionLogicWrapper>
    )
}

export function TextDisplayPropertiesLoading(): JSX.Element {
    return (
        <ExceptionLogicWrapper eventName="javascript_resolved">
            <StackTraceRawDisplay />
        </ExceptionLogicWrapper>
    )
}

export function TextDisplayWithStacktrace(): JSX.Element {
    return (
        <StacktraceWrapperAllEvents>
            <StackTraceRawDisplay />
        </StacktraceWrapperAllEvents>
    )
}

//////////////////// Utils

function StacktraceWrapperAllEvents({ children }: { children: JSX.Element }): JSX.Element {
    const eventNames = Object.keys(TEST_EVENTS) as TestEventName[]
    return (
        <div className="space-y-4">
            {eventNames.map((name: TestEventName) => {
                return (
                    <ExceptionLogicWrapper key={name} eventName={name}>
                        <LemonCard hoverEffect={false} className="p-2">
                            {children}
                        </LemonCard>
                    </ExceptionLogicWrapper>
                )
            })}
        </div>
    )
}

function StackTraceGenericDisplay({ className }: { className?: string }): JSX.Element {
    const { showAllFrames } = useValues(exceptionCardLogic)
    const { setShowAllFrames } = useActions(exceptionCardLogic)
    return (
        <CollapsibleExceptionList
            showAllFrames={showAllFrames}
            setShowAllFrames={setShowAllFrames}
            className={className}
        />
    )
}

function StackTraceRawDisplay({ className }: { className?: string }): JSX.Element {
    const { showAllFrames } = useValues(exceptionCardLogic)
    const { setShowAllFrames } = useActions(exceptionCardLogic)
    return <RawExceptionList showAllFrames={showAllFrames} setShowAllFrames={setShowAllFrames} className={className} />
}
