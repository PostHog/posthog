import { useMountedLogic, useValues } from 'kea'
import { useMemo, useState } from 'react'

import { LemonButton, LemonInput, LemonSkeleton, Link } from '@posthog/lemon-ui'

import { LemonMenu } from 'lib/lemon-ui/LemonMenu'
import { LemonMenuItems } from 'lib/lemon-ui/LemonMenu'
import { urls } from 'scenes/urls'

import { byokModelPickerLogic } from './byokModelPickerLogic'

export interface ByokModelPickerProps {
    model: string
    selectedProviderKeyId: string | null
    onSelect: (modelId: string, providerKeyId: string) => void
    placeholder?: string
    selectedModelName?: string
    'data-attr'?: string
}

export function ByokModelPicker({
    model,
    selectedProviderKeyId,
    onSelect,
    placeholder = 'Select model',
    selectedModelName,
    'data-attr': dataAttr,
}: ByokModelPickerProps): JSX.Element {
    useMountedLogic(byokModelPickerLogic)
    const { providerModelGroups, byokModelsLoading, providerKeysLoading } = useValues(byokModelPickerLogic)
    const [search, setSearch] = useState('')
    const lowerSearch = search.toLowerCase()

    const menuItems: LemonMenuItems = useMemo(() => {
        const filteredGroups = providerModelGroups
            .map((group) => {
                const filteredModels = lowerSearch
                    ? group.models.filter(
                          (m) => m.name.toLowerCase().includes(lowerSearch) || m.id.toLowerCase().includes(lowerSearch)
                      )
                    : group.models
                return { ...group, models: filteredModels }
            })
            .filter((group) => group.models.length > 0)

        const items: LemonMenuItems = [
            {
                label: () => (
                    <div className="px-1 py-1" onClick={(e) => e.stopPropagation()}>
                        <LemonInput
                            type="search"
                            placeholder="Find a model..."
                            value={search}
                            onChange={setSearch}
                            fullWidth
                            size="small"
                            autoFocus
                        />
                    </div>
                ),
            },
            ...filteredGroups.map((group): LemonMenuItems[number] => {
                const isActiveGroup = group.providerKeyId === selectedProviderKeyId
                return {
                    label: group.label,
                    active: isActiveGroup && group.models.some((m) => m.id === model),
                    items: group.models.map((m) => ({
                        label: m.name,
                        tooltip: m.description || undefined,
                        active: isActiveGroup && m.id === model,
                        onClick: () => onSelect(m.id, group.providerKeyId),
                    })),
                }
            }),
            {
                label: () => (
                    <div className="px-2 py-1.5 border-t">
                        <Link to={urls.settings('environment-llm-analytics', 'llm-analytics-byok')} className="text-xs">
                            Configure AI providers
                        </Link>
                    </div>
                ),
            },
        ]
        return items
    }, [providerModelGroups, model, selectedProviderKeyId, search, lowerSearch, onSelect])

    if (byokModelsLoading || providerKeysLoading) {
        return <LemonSkeleton className="h-10" />
    }

    return (
        <LemonMenu items={menuItems} closeOnClickInside placement="bottom-start">
            <LemonButton type="secondary" fullWidth className="justify-between" data-attr={dataAttr}>
                {selectedModelName ?? placeholder}
            </LemonButton>
        </LemonMenu>
    )
}
