import type { ReactElement } from 'react'

import { DataTable, type DataTableColumn } from '@posthog/mcp-ui'
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@posthog/quill'

import { RolloutBar } from './RolloutBar'

export interface Variant {
    key: string
    name?: string
    rollout_percentage: number
}

export interface VariantTableProps {
    variants: Variant[]
}

const columns: DataTableColumn<Variant>[] = [
    {
        key: 'key',
        header: 'Key',
        render: (row) => <span className="font-mono text-xs">{row.key}</span>,
    },
    {
        key: 'name',
        header: 'Name',
        render: (row) => <span className="text-muted-foreground">{row.name || '—'}</span>,
    },
    {
        key: 'rollout_percentage',
        header: (
            <TooltipProvider>
                <Tooltip>
                    <TooltipTrigger
                        render={
                            <span className="cursor-default border-b border-dashed border-muted-foreground">
                                Rollout
                            </span>
                        }
                    />
                    <TooltipContent side="bottom">Traffic distribution among variants</TooltipContent>
                </Tooltip>
            </TooltipProvider>
        ),
        render: (row) => <RolloutBar percentage={row.rollout_percentage} />,
    },
]

export function VariantTable({ variants }: VariantTableProps): ReactElement {
    return <DataTable<Variant> columns={columns} data={variants} pageSize={0} emptyMessage="No variants" />
}
