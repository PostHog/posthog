import { useActions, useValues } from 'kea'

import { LemonDivider, LemonSelect } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'

import { SceneSection } from '~/layout/scenes/components/SceneSection'

import { endpointLogic } from './endpointLogic'

interface EndpointConfigurationProps {
    tabId: string
}

type CacheAgeOption = number | null

const CACHE_AGE_OPTIONS: { value: CacheAgeOption; label: string }[] = [
    { value: null, label: 'Default caching behavior' },
    { value: 300, label: '5 minutes' },
    { value: 900, label: '15 minutes' },
    { value: 1800, label: '30 minutes' },
    { value: 3600, label: '1 hour' },
    { value: 10800, label: '3 hours' },
    { value: 86400, label: '1 day' },
    { value: 259200, label: '3 days' },
]

export function EndpointConfiguration({ tabId }: EndpointConfigurationProps): JSX.Element {
    const { endpoint, cacheAge } = useValues(endpointLogic({ tabId }))
    const { setCacheAge } = useActions(endpointLogic({ tabId }))

    if (!endpoint) {
        return <></>
    }

    return (
        <SceneSection title="Configure this endpoint">
            <div className="flex flex-col gap-4 max-w-2xl">
                <LemonField.Pure
                    label="Cache age"
                    info="Cache age defines how long your endpoint will return cached results before running the query again
                    and refreshing the results."
                >
                    <LemonSelect value={cacheAge} onChange={setCacheAge} options={CACHE_AGE_OPTIONS} />
                </LemonField.Pure>
            </div>
            <LemonDivider />
        </SceneSection>
    )
}
