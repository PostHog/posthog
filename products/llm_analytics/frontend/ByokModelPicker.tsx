import { useActions, useMountedLogic, useValues } from 'kea'

import { IconChevronDown, IconChevronRight } from '@posthog/icons'
import { LemonButton, LemonInput, LemonSkeleton, Link } from '@posthog/lemon-ui'

import { LemonMenu, LemonMenuItem, LemonMenuItems } from 'lib/lemon-ui/LemonMenu'
import { urls } from 'scenes/urls'

import { byokModelPickerLogic } from './byokModelPickerLogic'
import { ModelOption } from './llmAnalyticsPlaygroundLogic'
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
    const {
        search,
        filteredProviderModelGroups,
        selectedProviderForModel,
        byokModelsLoading,
        providerKeysLoading,
        isProviderExpanded,
        hasExplicitExpandState,
    } = useValues(byokModelPickerLogic)
    const { setSearch, clearSearch, toggleProviderExpanded } = useActions(byokModelPickerLogic)

    const selectedProvider = selectedProviderForModel(model, selectedProviderKeyId)

    const handleVisibilityChange = (visible: boolean): void => {
        if (!visible) {
            clearSearch()
        }
    }

    if (byokModelsLoading || providerKeysLoading) {
        return <LemonSkeleton className="h-10" />
    }

    const isSearching = search.length > 0

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
            if (group.disabled) {
                return {
                    icon: <LLMProviderIcon provider={group.provider} />,
                    label: group.label,
                    disabledReason: 'This provider key has an issue. Check your provider settings.',
                }
            }

            const isActiveGroup = group.providerKeyId === selectedProviderKeyId

            const buildModelItem = (m: ModelOption): LemonMenuItem => ({
                icon: <LLMProviderIcon provider={group.provider} />,
                label: m.name,
                tooltip: m.description || undefined,
                active: isActiveGroup && m.id === model,
                onClick: () => onSelect(m.id, group.providerKeyId),
            })

            const recommended = group.models.filter((m) => m.isRecommended)
            const other = group.models.filter((m) => !m.isRecommended)
            const hasOther = other.length > 0
            const hasRecommended = recommended.length > 0

            // When searching or no split needed, show all models flat
            if (isSearching || !hasOther || !hasRecommended) {
                return {
                    icon: <LLMProviderIcon provider={group.provider} />,
                    label: group.label,
                    active: isActiveGroup && group.models.some((m) => m.id === model),
                    items: group.models.map(buildModelItem),
                }
            }

            // Auto-expand when the selected model is in the collapsed section,
            // but only as a default — once the user explicitly toggles, respect their choice.
            const selectedIsHidden = isActiveGroup && other.some((m) => m.id === model)
            const expanded = hasExplicitExpandState(group.providerKeyId)
                ? isProviderExpanded(group.providerKeyId)
                : selectedIsHidden

            return {
                icon: <LLMProviderIcon provider={group.provider} />,
                label: group.label,
                active: isActiveGroup && group.models.some((m) => m.id === model),
                items: [
                    ...recommended.map(buildModelItem),
                    {
                        label: () => (
                            <div className="click-outside-block">
                                <LemonButton
                                    size="xsmall"
                                    fullWidth
                                    icon={expanded ? <IconChevronDown /> : <IconChevronRight />}
                                    onClick={() => toggleProviderExpanded(group.providerKeyId)}
                                >
                                    <span className="text-xs text-secondary">
                                        {expanded ? 'Hide' : 'Show'} {other.length} more{' '}
                                        {other.length === 1 ? 'model' : 'models'}
                                    </span>
                                </LemonButton>
                            </div>
                        ),
                    },
                    ...(expanded ? other.map(buildModelItem) : []),
                ],
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
                {selectedModelName ?? (model || placeholder)}
            </LemonButton>
        </LemonMenu>
    )
}
