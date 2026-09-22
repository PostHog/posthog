import { type ReactElement, type ReactNode } from 'react'

import { DataTable, type DataTableColumn, ListDetailView } from '@posthog/mcp-ui'
import { Badge, Button } from '@posthog/quill'

import {
    VisionObservationView,
    type VisionObservationData,
    observationHeadline,
    statusVariant,
} from './VisionObservationView'

export interface VisionObservationListData {
    count?: number
    results: VisionObservationData[]
    _posthogUrl?: string
}

export interface VisionObservationListViewProps {
    data: VisionObservationListData
    onVisionObservationClick?: (observation: VisionObservationData) => Promise<VisionObservationData | null>
}

export function VisionObservationListView({
    data,
    onVisionObservationClick,
}: VisionObservationListViewProps): ReactElement {
    const pending = data.results.filter((o) => o.status === 'pending' || o.status === 'running').length

    return (
        <ListDetailView<VisionObservationData>
            onItemClick={onVisionObservationClick}
            backLabel="All observations"
            getItemName={(observation) => observationHeadline(observation)}
            renderDetail={(observation) => <VisionObservationView data={observation} />}
            renderList={(handleClick) => {
                const columns: DataTableColumn<VisionObservationData>[] = [
                    {
                        key: 'result',
                        header: 'Result',
                        render: (row): ReactNode =>
                            onVisionObservationClick ? (
                                <Button
                                    variant="link"
                                    size="sm"
                                    onClick={() => handleClick(row)}
                                    className="h-auto px-0 text-left max-w-md truncate"
                                >
                                    {observationHeadline(row)}
                                </Button>
                            ) : (
                                <span className="max-w-md truncate block">{observationHeadline(row)}</span>
                            ),
                    },
                    {
                        key: 'status',
                        header: 'Status',
                        sortable: true,
                        render: (row): ReactNode => (
                            <Badge variant={statusVariant[row.status] ?? 'default'}>{row.status}</Badge>
                        ),
                    },
                    {
                        key: 'session_id',
                        header: 'Session',
                        render: (row): ReactNode => <span className="text-xs break-all">{row.session_id}</span>,
                    },
                ]

                return (
                    <div className="p-4">
                        <div className="flex flex-col gap-2">
                            <span className="text-sm text-muted-foreground">
                                {data.results.length} observation{data.results.length === 1 ? '' : 's'}
                                {/* Say what is still coming, so a partial list does not read as the final answer. */}
                                {pending > 0 ? `, ${pending} still running` : ''}
                            </span>
                            <DataTable<VisionObservationData>
                                columns={columns}
                                data={data.results}
                                pageSize={10}
                                emptyMessage="No observations yet"
                            />
                        </div>
                    </div>
                )
            }}
        />
    )
}
