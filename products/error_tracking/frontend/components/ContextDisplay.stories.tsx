import { LemonCard } from '@posthog/lemon-ui'
import { Meta } from '@storybook/react'

import { TEST_EVENTS, TestEventName } from '../__mocks__/events'
import { ContextTable, ContextTableProps } from './ContextDisplay'
import { identifierToHuman } from 'lib/utils'

const meta: Meta = {
    title: 'ErrorTracking/ContextDisplay',
    parameters: {
        layout: 'centered',
        viewMode: 'story',
    },
    decorators: [
        (Story: React.FC): JSX.Element => {
            return (
                <LemonCard hoverEffect={false} className="p-2 px-3 w-[900px]">
                    <Story />
                </LemonCard>
            )
        },
    ],
}

export default meta

///////////////////// Context Display

export function ContextDisplayEmpty(): JSX.Element {
    return <ContextTable entries={[]} />
}

export function ContextDisplayWithStacktrace(): JSX.Element {
    return <ContextWrapperAllEvents>{(props) => <ContextTable {...props} />}</ContextWrapperAllEvents>
}

//////////////////// Utils

function getProps(event_name: TestEventName): ContextTableProps {
    const properties = event_name ? TEST_EVENTS[event_name].properties : {}
    const entries = Object.entries(properties).map(
        ([key, value]) => [identifierToHuman(key, 'title'), value] as [string, unknown]
    )

    return { entries }
}

function ContextWrapperAllEvents({ children }: { children: (props: ContextTableProps) => JSX.Element }): JSX.Element {
    const eventNames = Object.keys(TEST_EVENTS) as TestEventName[]
    return (
        <div className="space-y-4">
            {eventNames.map((name: TestEventName) => {
                const props = getProps(name)
                return (
                    <div className="px-3 py-2" key={name}>
                        {children(props)}
                    </div>
                )
            })}
        </div>
    )
}
