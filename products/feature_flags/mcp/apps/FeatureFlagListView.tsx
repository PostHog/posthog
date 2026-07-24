import { type ReactElement, type ReactNode } from 'react'

import { DataTable, type DataTableColumn, ListDetailView, formatDate } from '@posthog/mcp-ui'
import { Badge, Button } from '@posthog/quill'

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

export function FeatureFlagListView({ data, onFlagClick }: FeatureFlagListViewProps): ReactElement {
    return (
        <ListDetailView<FeatureFlagData>
            onItemClick={onFlagClick}
            backLabel="All flags"
            getItemName={(flag) => flag.key}
            renderDetail={(flag) => <FeatureFlagView flag={flag} />}
            renderList={(handleClick) => {
                const columns: DataTableColumn<FeatureFlagData>[] = [
                    {
                        key: 'key',
                        header: 'Key',
                        sortable: true,
                        render: (row): ReactNode =>
                            onFlagClick ? (
                                <Button
                                    variant="link"
                                    size="sm"
                                    onClick={() => handleClick(row)}
                                    className="h-auto px-0 text-left"
                                >
                                    {row.key}
                                </Button>
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
                            <Badge variant={row.active ? 'success' : 'default'}>
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
                                            <Badge key={v.key} variant="info">
                                                {v.key}: {v.rollout_percentage}%
                                            </Badge>
                                        ))}
                                    </div>
                                )
                            }

                            if (groups.length > 0) {
                                const rollout = groups[0]!.rollout_percentage
                                return <RolloutBar percentage={rollout ?? 0} className="min-w-25" />
                            }

                            return <span className="text-muted-foreground">&mdash;</span>
                        },
                    },
                    {
                        key: 'tags',
                        header: 'Tags',
                        render: (row): ReactNode =>
                            row.tags?.length ? (
                                <div className="flex gap-1 flex-wrap">
                                    {row.tags.map((tag) => (
                                        <Badge key={tag}>{tag}</Badge>
                                    ))}
                                </div>
                            ) : (
                                <span className="text-muted-foreground">&mdash;</span>
                            ),
                    },
                    {
                        key: 'updated_at',
                        header: 'Last updated',
                        sortable: true,
                        render: (row): ReactNode =>
                            row.updated_at ? (
                                <span className="text-muted-foreground">{formatDate(row.updated_at)}</span>
                            ) : (
                                <span className="text-muted-foreground">&mdash;</span>
                            ),
                    },
                ]

                return (
                    <div className="p-4">
                        <div className="flex flex-col gap-2">
                            <div className="flex items-center justify-between">
                                <span className="text-sm text-muted-foreground">
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
                        </div>
                    </div>
                )
            }}
        />
    )
}
