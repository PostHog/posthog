import { Meta } from '@storybook/react'

import { LemonCard } from '@posthog/lemon-ui'

import { getAdditionalProperties } from 'lib/components/Errors/utils'

import { TEST_EVENTS, TestEventName } from '../../__mocks__/events'
import { ContextDisplay, ContextDisplayProps } from './ContextDisplay'

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
    return <ContextDisplay loading={false} properties={{}} additionalProperties={{}} />
}

export function ContextDisplayWithStacktrace(): JSX.Element {
    return <ContextWrapperAllEvents>{(props) => <ContextDisplay {...props} />}</ContextWrapperAllEvents>
}

export function ContextDisplayMisc(): JSX.Element {
    return (
        <ContextDisplay
            loading={false}
            properties={{}}
            additionalProperties={{
                undefined_value: undefined,
                null_value: null,
                number: 123,
                string: 'value',
                array: ['item-1', 'item-2'],
                url: 'https://example.com',
                object: { key: 'value', 'nested-object': { key: 'value' } },
            }}
        />
    )
}

export function ContextDisplayShowAllProperties(): JSX.Element {
    return (
        <div className="w-[900px]">
            <ContextDisplay
                loading={false}
                properties={{
                    $browser: 'Chrome',
                    $browser_version: '134',
                    $exception_level: 'error',
                    $request_params: { page: 2, filters: { status: ['open', 'pending'] } },
                    $job_metadata: [{ attempt: 1, scheduled_at: '2026-01-01T00:00:00Z' }],
                    $sdk_debug: false,
                    plan: 'business',
                }}
                additionalProperties={{ plan: 'business' }}
                showAllProperties
            />
        </div>
    )
}
ContextDisplayShowAllProperties.parameters = { testOptions: { snapshotBrowsers: [] } }

//////////////////// Utils

function getProps(event_name: TestEventName): ContextDisplayProps {
    const properties = event_name ? TEST_EVENTS[event_name].properties : {}
    const additionalProperties = getAdditionalProperties(properties, true)

    return { loading: false, properties, additionalProperties }
}

function ContextWrapperAllEvents({ children }: { children: (props: ContextDisplayProps) => JSX.Element }): JSX.Element {
    const eventNames = Object.keys(TEST_EVENTS) as TestEventName[]
    return (
        <div className="space-y-4">
            {eventNames.map((name: TestEventName) => {
                const props = getProps(name)
                return (
                    <LemonCard key={name} hoverEffect={false} className="p-0 w-[900px]">
                        {children(props)}
                    </LemonCard>
                )
            })}
        </div>
    )
}
