import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { LemonSelect } from '@posthog/lemon-ui'

import type { CustomInputRendererProps } from 'lib/components/CyclotronJob/customInputRenderers'

import {
    LLM_PROVIDER_LABELS,
    llmProviderKeysLogic,
    sortProviderKeys,
} from 'products/llm_analytics/frontend/settings/llmProviderKeysLogic'

export default function CyclotronJobInputLLMProviderKey({ value, onChange }: CustomInputRendererProps): JSX.Element {
    const { providerKeys, providerKeysLoading } = useValues(llmProviderKeysLogic)
    const { loadProviderKeys } = useActions(llmProviderKeysLogic)

    useEffect(() => {
        if (providerKeys.length === 0 && !providerKeysLoading) {
            loadProviderKeys()
        }
    }, [providerKeys.length, loadProviderKeys, providerKeysLoading])

    const usableKeys = sortProviderKeys(providerKeys).filter((key) => key.state !== 'invalid')

    const options = usableKeys.map((key) => ({
        value: key.id,
        label: `${key.name} (${LLM_PROVIDER_LABELS[key.provider] ?? key.provider})`,
    }))

    return (
        <LemonSelect
            fullWidth
            options={options}
            value={value}
            onChange={onChange}
            loading={providerKeysLoading}
            placeholder="Select a provider key..."
        />
    )
}
