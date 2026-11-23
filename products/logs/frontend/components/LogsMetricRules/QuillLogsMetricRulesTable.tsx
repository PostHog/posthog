import { useActions, useValues } from 'kea'
import { useMemo } from 'react'

import { IconEllipsis, IconPlus } from '@posthog/icons'
import {
    Badge,
    Button,
    DataTable,
    DataTableProps,
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuTrigger,
    Skeleton,
    Switch,
    Text,
} from '@posthog/quill'

import { LogsMetricRuleApi } from 'products/logs/frontend/generated/api.schemas'

import { logsMetricRulesSectionLogic } from './logsMetricRulesSectionLogic'

export function QuillLogsMetricRulesTable(): JSX.Element {
    const { rules, rulesLoading } = useValues(logsMetricRulesSectionLogic)
    const { openNewRuleModal, openEditRuleModal, deleteRule, setRuleEnabled } = useActions(logsMetricRulesSectionLogic)

    const columns = useMemo<DataTableProps<LogsMetricRuleApi, unknown>['columns']>(
        () => [
            {
                id: 'name',
                header: 'Name',
                enableSorting: false,
                meta: { expand: true },
                cell: ({ row }) => (
                    <Text size="xs" weight="medium" render={<span />}>
                        {row.original.name}
                    </Text>
                ),
            },
            {
                id: 'metric_name',
                header: 'Metric',
                enableSorting: false,
                cell: ({ row }) => <code>{row.original.metric_name}</code>,
            },
            {
                id: 'type',
                header: 'Type',
                enableSorting: false,
                cell: ({ row }) =>
                    row.original.value_attribute ? (
                        <Badge variant="info">{row.original.value_attribute}</Badge>
                    ) : (
                        <Badge>count</Badge>
                    ),
            },
            {
                id: 'group_by',
                header: 'Group by',
                enableSorting: false,
                cell: ({ row }) => (
                    <Text size="xs" variant={row.original.group_by?.length ? 'default' : 'muted'} render={<span />}>
                        {row.original.group_by?.length ? row.original.group_by.join(', ') : '–'}
                    </Text>
                ),
            },
            {
                id: 'enabled',
                header: 'Enabled',
                enableSorting: false,
                cell: ({ row }) => (
                    <Switch
                        checked={row.original.enabled ?? false}
                        onCheckedChange={(checked) => setRuleEnabled(row.original, checked)}
                        aria-label={`Enable ${row.original.name}`}
                    />
                ),
            },
            {
                id: 'actions',
                header: '',
                enableSorting: false,
                meta: { align: 'right' },
                cell: ({ row }) => (
                    <DropdownMenu>
                        <DropdownMenuTrigger
                            render={
                                <Button
                                    size="icon"
                                    aria-label={`More options for ${row.original.name}`}
                                    tooltip={`More options for ${row.original.name}`}
                                />
                            }
                        >
                            <IconEllipsis />
                        </DropdownMenuTrigger>
                        <DropdownMenuContent align="end">
                            <DropdownMenuItem onClick={() => openEditRuleModal(row.original)}>Edit</DropdownMenuItem>
                            <DropdownMenuItem variant="destructive" onClick={() => deleteRule(row.original)}>
                                Delete
                            </DropdownMenuItem>
                        </DropdownMenuContent>
                    </DropdownMenu>
                ),
            },
        ],
        [openEditRuleModal, deleteRule, setRuleEnabled]
    )

    return (
        <div className="flex flex-col gap-2">
            {rulesLoading && rules.length === 0 ? (
                <div className="flex flex-col gap-2">
                    <Skeleton className="h-8 w-full" />
                    <Skeleton className="h-8 w-full" />
                    <Skeleton className="h-8 w-full" />
                </div>
            ) : (
                <DataTable
                    columns={columns}
                    data={rules}
                    getRowId={(rule) => rule.id}
                    fullWidth
                    empty={
                        <Text size="xs" variant="muted" render={<span />}>
                            No log-based metrics yet. Create one to start generating metrics from your logs.
                        </Text>
                    }
                />
            )}
            <div>
                <Button variant="primary" onClick={openNewRuleModal}>
                    <IconPlus />
                    New log-based metric
                </Button>
            </div>
        </div>
    )
}
