import { useMemo, useState } from 'react'

import { IconChevronDown, IconChevronRight } from '@posthog/icons'
import { LemonButton, LemonInput, LemonSkeleton, Link } from '@posthog/lemon-ui'

import { LemonMenu, LemonMenuItem, LemonMenuItems } from 'lib/lemon-ui/LemonMenu'

import { urls } from '~/scenes/urls'

import { LLMProviderIcon } from './LLMProviderIcon'
import { type ModelOption, type ProviderModelGroup } from './modelPickerLogic'
import { type LLMProvider, toLLMProvider } from './settings/llmProviderKeysLogic'

const PROVIDER_SETTINGS_URL = urls.settings('environment-llm-analytics', 'llm-analytics-byok')

export function getModelPickerFooterLink(hasByokKeys: boolean): { label: string; to: string } {
    return {
        label: hasByokKeys ? 'Configure AI providers' : 'Add your own API keys',
        to: PROVIDER_SETTINGS_URL,
    }
}

export function parseTrialProviderKeyId(providerKeyId: string): LLMProvider | null {
    return providerKeyId.startsWith('trial:') ? toLLMProvider(providerKeyId.slice(6)) : null
}

export interface ModelPickerProps {
    model: string
    selectedProviderKeyId: string | null
    onSelect: (modelId: string, providerKeyId: string) => void
    groups: ProviderModelGroup[]
    loading?: boolean
    footerLink?: { label: string; to: string } | null
    placeholder?: string
    selectedModelName?: string
    'data-attr'?: string
}

export function findSelectedProvider(
    groups: ProviderModelGroup[],
    model: string,
    providerKeyId: string | null
): LLMProvider | null {
    // Try exact match on providerKeyId first
    const exactMatch = groups.find((g) => g.providerKeyId === providerKeyId && g.models.some((m) => m.id === model))
    if (exactMatch) {
        return exactMatch.provider
    }
    // Fall back to matching by model id alone (e.g., trial mode where providerKeyId is null)
    const modelMatch = groups.find((g) => g.models.some((m) => m.id === model))
    return modelMatch?.provider ?? null
}

export function filterGroups(groups: ProviderModelGroup[], search: string): ProviderModelGroup[] {
    if (!search) {
        return groups
    }
    const lower = search.toLowerCase()
    return groups
        .map((group) => ({
            ...group,
            models: group.models.filter(
                (m) => m.name.toLowerCase().includes(lower) || m.id.toLowerCase().includes(lower)
            ),
        }))
        .filter((group) => group.models.length > 0)
}

export function ModelPicker({
    model,
    selectedProviderKeyId,
    onSelect,
    groups,
    loading = false,
    footerLink,
    placeholder = 'Select model',
    selectedModelName,
    'data-attr': dataAttr,
}: ModelPickerProps): JSX.Element {
    const [search, setSearch] = useState('')
    const [expandedProviders, setExpandedProviders] = useState<Record<string, boolean>>({})

    const filteredGroups = useMemo(() => filterGroups(groups, search), [groups, search])
    const selectedProvider = useMemo(
        () => findSelectedProvider(groups, model, selectedProviderKeyId),
        [groups, model, selectedProviderKeyId]
    )

    const toggleProviderExpanded = (providerKeyId: string): void => {
        setExpandedProviders((prev) => ({ ...prev, [providerKeyId]: !prev[providerKeyId] }))
    }

    const handleVisibilityChange = (visible: boolean): void => {
        if (!visible) {
            setSearch('')
        }
    }

    if (loading) {
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
        ...filteredGroups.map((group): LemonMenuItems[number] => {
            if (group.disabled) {
                return {
                    icon: <LLMProviderIcon provider={group.provider} />,
                    label: group.label,
                    disabledReason: 'This provider key has an issue. Check your provider settings.',
                }
            }

            const isActiveGroup =
                group.providerKeyId === selectedProviderKeyId ||
                (selectedProviderKeyId === null && group.models.some((m) => m.id === model))

            const buildModelItem = (m: ModelOption): LemonMenuItem => ({
                icon: <LLMProviderIcon provider={group.provider} />,
                label: m.name,
                tooltip: m.description || undefined,
                active: m.id === model && isActiveGroup,
                onClick: () => onSelect(m.id, group.providerKeyId),
            })

            const recommended = group.models.filter((m) => m.isRecommended)
            const other = group.models.filter((m) => !m.isRecommended)
            const hasOther = other.length > 0
            const hasRecommended = recommended.length > 0

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
            const hasExplicitState = group.providerKeyId in expandedProviders
            const expanded = hasExplicitState ? !!expandedProviders[group.providerKeyId] : selectedIsHidden

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
        ...(footerLink
            ? [
                  {
                      label: () => (
                          <div className="px-2 py-1.5 border-t">
                              <Link to={footerLink.to} className="text-xs">
                                  {footerLink.label}
                              </Link>
                          </div>
                      ),
                  },
              ]
            : []),
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
