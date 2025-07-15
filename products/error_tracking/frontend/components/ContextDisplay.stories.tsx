import { LemonCard } from '@posthog/lemon-ui'
import { Meta } from '@storybook/react'

import { TEST_EVENTS, TestEventName } from '../__mocks__/events'
import { ContextDisplay, ContextDisplayProps } from './ContextDisplay'
import { getAdditionalProperties, getExceptionAttributes } from 'lib/components/Errors/utils'

const meta: Meta = {
    title: 'ErrorTracking/ContextDisplay',
    parameters: {
        layout: 'centered',
        viewMode: 'story',
    },
}

export default meta

///////////////////// Context Display

export function ContextDisplayEmpty(): JSX.Element {
    return <ContextDisplay loading={false} exceptionAttributes={{}} additionalProperties={{}} />
}

export function ContextDisplayWithStacktrace(): JSX.Element {
    return <ContextWrapperAllEvents>{(props) => <ContextDisplay {...props} />}</ContextWrapperAllEvents>
}

//////////////////// Utils

function getProps(event_name: TestEventName): ContextDisplayProps {
    const properties = event_name ? TEST_EVENTS[event_name].properties : {}
    const exceptionAttributes = properties ? getExceptionAttributes(properties) : null
    const additionalProperties = getAdditionalProperties(properties, true)

    return { loading: false, exceptionAttributes, additionalProperties }
}

function ContextWrapperAllEvents({ children }: { children: (props: ContextDisplayProps) => JSX.Element }): JSX.Element {
    const eventNames = Object.keys(TEST_EVENTS) as TestEventName[]
    return (
        <div className="space-y-4">
            {eventNames.map((name: TestEventName) => {
                const props = getProps(name)
                return (
                    <LemonCard hoverEffect={false} className="p-0 w-[900px]">
                        {children(props)}
                    </LemonCard>
                )
            })}
        </div>
    )
}
