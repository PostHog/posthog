import { useActions, useValues } from 'kea'

import { LemonSelect } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'

import { endpointLogic } from './endpointLogic'

interface EndpointConfigurationProps {
    tabId: string
}

type DataFreshnessOption = '5m' | '15m' | '30m' | '1h' | '3h' | '24h'

const DATA_FRESHNESS_OPTIONS: { value: DataFreshnessOption; label: string }[] = [
    { value: '5m', label: '5 minutes' },
    { value: '15m', label: '15 minutes' },
    { value: '30m', label: '30 minutes' },
    { value: '1h', label: '1 hour' },
    { value: '3h', label: '3 hours' },
    { value: '24h', label: 'Daily' },
]

export function EndpointConfiguration({ tabId }: EndpointConfigurationProps): JSX.Element {
    const { endpoint } = useValues(endpointLogic({ tabId }))
    const { updateEndpoint } = useActions(endpointLogic({ tabId }))

    if (!endpoint) {
        return <></>
    }

    const handleDataFreshnessChange = (): void => {
        updateEndpoint(endpoint.name, { ...endpoint.parameters })
    }

    return (
        <div className="flex flex-col gap-4 max-w-2xl">
            <LemonField.Pure label="Data freshness">
                <LemonSelect
                    // value={}
                    onChange={handleDataFreshnessChange}
                    options={DATA_FRESHNESS_OPTIONS}
                />
            </LemonField.Pure>
            <div className="text-xs text-secondary -mt-2">
                We will refresh this query to be readily available at this frequency.
            </div>
        </div>
    )
}
