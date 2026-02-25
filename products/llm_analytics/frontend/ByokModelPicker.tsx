import { useActions, useMountedLogic, useValues } from 'kea'

import { LemonButton, LemonInput, LemonSkeleton, Link } from '@posthog/lemon-ui'

import { LemonMenu, LemonMenuItems } from 'lib/lemon-ui/LemonMenu'
import { urls } from 'scenes/urls'

import { byokModelPickerLogic } from './byokModelPickerLogic'
import { LLMProviderIcon } from './LLMProviderIcon'

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
    const { search, filteredProviderModelGroups, selectedProviderForModel, byokModelsLoading, providerKeysLoading } =
        useValues(byokModelPickerLogic)
    const { setSearch, clearSearch } = useActions(byokModelPickerLogic)

    const selectedProvider = selectedProviderForModel(model, selectedProviderKeyId)

    const handleVisibilityChange = (visible: boolean): void => {
        if (!visible) {
            clearSearch()
        }
    }

    if (byokModelsLoading || providerKeysLoading) {
        return <LemonSkeleton className="h-10" />
    }

    const menuItems: LemonMenuItems = [
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
        ...filteredProviderModelGroups.map((group): LemonMenuItems[number] => {
            const isActiveGroup = group.providerKeyId === selectedProviderKeyId
            return {
                icon: <LLMProviderIcon provider={group.provider} />,
                label: group.label,
                active: isActiveGroup && group.models.some((m) => m.id === model),
                items: group.models.map((m) => ({
                    icon: <LLMProviderIcon provider={group.provider} />,
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

    return (
        <LemonMenu
            items={menuItems}
            closeOnClickInside
            placement="bottom-start"
            onVisibilityChange={handleVisibilityChange}
        >
            <LemonButton
                type="secondary"
                fullWidth
                className="justify-between"
                data-attr={dataAttr}
                icon={selectedProvider ? <LLMProviderIcon provider={selectedProvider} /> : undefined}
            >
                {selectedModelName ?? placeholder}
            </LemonButton>
        </LemonMenu>
    )
}
