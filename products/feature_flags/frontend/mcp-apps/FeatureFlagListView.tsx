import { type ReactElement, type ReactNode, useCallback, useState } from 'react'

import { BackButton, Badge, DataTable, type DataTableColumn, formatDate, LoadingState, Stack } from '@posthog/mosaic'

import { FeatureFlagView, type FeatureFlagData } from './FeatureFlagView'
import { RolloutBar } from './RolloutBar'

export interface FeatureFlagListData {
    count: number
    results: FeatureFlagData[]
    next: string | null
    previous: string | null
    _posthogUrl?: string
}

export interface FeatureFlagListViewProps {
    data: FeatureFlagListData
    onFlagClick?: (flag: FeatureFlagData) => Promise<FeatureFlagData | null>
}

type ViewState = { view: 'list' } | { view: 'loading'; flagKey: string } | { view: 'detail'; flag: FeatureFlagData }

export function FeatureFlagListView({ data, onFlagClick }: FeatureFlagListViewProps): ReactElement {
    const [viewState, setViewState] = useState<ViewState>({ view: 'list' })

    const handleFlagClick = useCallback(
        async (flag: FeatureFlagData) => {
            if (!onFlagClick) {
                return
            }

            setViewState({ view: 'loading', flagKey: flag.key })
            const detail = await onFlagClick(flag).catch((error) => {
                console.error('Error loading feature flag detail:', error)
                return null
            })

            if (detail) {
                setViewState({ view: 'detail', flag: detail })
            } else {
                setViewState({ view: 'list' })
            }
        },
        [onFlagClick]
    )

    const handleBack = useCallback(() => setViewState({ view: 'list' }), [])

    if (viewState.view === 'loading') {
        return (
            <div className="p-4">
                <Stack gap="sm">
                    <BackButton onClick={handleBack} label="All flags" />
                    <LoadingState label={viewState.flagKey} />
                </Stack>
            </div>
        )
    }

    if (viewState.view === 'detail') {
        return (
            <div className="p-4">
                <Stack gap="sm">
                    <BackButton onClick={handleBack} label="All flags" />
                    <FeatureFlagView flag={viewState.flag} />
                </Stack>
            </div>
        )
    }

    const columns: DataTableColumn<FeatureFlagData>[] = [
        {
            key: 'key',
            header: 'Key',
            sortable: true,
            render: (row): ReactNode =>
                onFlagClick ? (
                    <button
                        onClick={() => handleFlagClick(row)}
                        className="text-link underline decoration-border-primary hover:decoration-link cursor-pointer text-left transition-colors"
                    >
                        {row.key}
                    </button>
                ) : (
                    row.key
                ),
        },
        {
            key: 'name',
            header: 'Name',
            sortable: true,
        },
        {
            key: 'active',
            header: 'Status',
            sortable: true,
            render: (row): ReactNode => (
                <Badge variant={row.active ? 'success' : 'neutral'} size="sm">
                    {row.active ? 'Active' : 'Inactive'}
                </Badge>
            ),
        },
        {
            key: 'filters' as keyof FeatureFlagData,
            header: 'Rollout',
            render: (row): ReactNode => {
                const variants = row.filters?.multivariate?.variants
                const groups = row.filters?.groups ?? []

                if (variants && variants.length > 0) {
                    return (
                        <div className="flex gap-1 flex-wrap">
                            {variants.map((v) => (
                                <Badge key={v.key} variant="info" size="sm">
                                    {v.key}: {v.rollout_percentage}%
                                </Badge>
                            ))}
                        </div>
                    )
                }

                if (groups.length > 0) {
                    const rollout = groups[0]!.rollout_percentage
                    return <RolloutBar percentage={rollout ?? 0} className="min-w-[100px]" />
                }

                return <span className="text-text-secondary">&mdash;</span>
            },
        },
        {
            key: 'tags',
            header: 'Tags',
            render: (row): ReactNode =>
                row.tags?.length ? (
                    <div className="flex gap-1 flex-wrap">
                        {row.tags.map((tag) => (
                            <Badge key={tag} variant="neutral" size="sm">
                                {tag}
                            </Badge>
                        ))}
                    </div>
                ) : (
                    <span className="text-text-secondary">&mdash;</span>
                ),
        },
        {
            key: 'updated_at',
            header: 'Last updated',
            sortable: true,
            render: (row): ReactNode =>
                row.updated_at ? (
                    <span className="text-text-secondary">{formatDate(row.updated_at)}</span>
                ) : (
                    <span className="text-text-secondary">&mdash;</span>
                ),
        },
    ]

    return (
        <div className="p-4">
            <Stack gap="sm">
                <div className="flex items-center justify-between">
                    <span className="text-sm text-text-secondary">
                        {data.count} {data.count === 1 ? 'flag' : 'flags'}
                    </span>
                </div>
                <DataTable<FeatureFlagData>
                    columns={columns}
                    data={data.results}
                    pageSize={10}
                    defaultSort={{ key: 'key', direction: 'asc' }}
                    emptyMessage="No feature flags found"
                />
            </Stack>
        </div>
    )
}
