import type { ColumnDef } from '@tanstack/react-table'
import { useActions } from 'kea'

import { Button, Text, Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill'

import { TZLabel } from 'lib/components/TZLabel'
import { LinkPrimitive } from 'lib/lemon-ui/Link'

import { ReleaseAllRow, releaseAllLogic } from './releaseAllLogic'
import { ReleaseAllOwner } from './ReleaseAllOwner'
import { ReleaseAllRowMenu } from './ReleaseAllRowMenu'
import { ReleaseAllStatus } from './ReleaseAllStatus'
import { RELEASE_ALL_TYPE_INFO } from './releaseAllTypeInfo'

export type ReleaseAllColumns = ColumnDef<ReleaseAllRow>[]

function ItemTitle({ row, position }: { row: ReleaseAllRow; position: number }): JSX.Element {
    const { itemOpened } = useActions(releaseAllLogic)
    const info = RELEASE_ALL_TYPE_INFO[row.type]
    return (
        <span className="flex min-w-0 items-center">
            <Tooltip>
                <TooltipTrigger
                    render={
                        <span
                            className="flex size-4 shrink-0 items-center justify-center [&_svg]:size-4"
                            // eslint-disable-next-line react/forbid-dom-props
                            style={{ color: info.color }}
                        />
                    }
                >
                    {info.icon}
                </TooltipTrigger>
                <TooltipContent>{info.label}</TooltipContent>
            </Tooltip>
            <Button
                variant="link-foreground"
                size="sm"
                nativeButton={false}
                left
                render={<LinkPrimitive to={row.href} />}
                className="min-w-0 shrink"
                data-attr="release-all-name"
                onClickCapture={() => itemOpened(row, position)}
                onAuxClick={(event) => event.button === 1 && itemOpened(row, position)}
            >
                <span className="truncate">{row.name}</span>
            </Button>
        </span>
    )
}

export function releaseAllColumns({ sortable }: { sortable: boolean }): ReleaseAllColumns {
    return [
        {
            id: 'name',
            minSize: 256,
            header: 'Title',
            meta: { expand: true },
            enableSorting: false,
            cell: ({ row }) => <ItemTitle row={row.original} position={row.index} />,
        },
        {
            id: 'status',
            header: 'Status',
            enableSorting: false,
            cell: ({ row }) => <ReleaseAllStatus row={row.original} />,
        },
        {
            id: 'owner',
            header: 'Owner',
            enableSorting: false,
            cell: ({ row }) => <ReleaseAllOwner owner={row.original.owner} />,
        },
        {
            id: 'created_at',
            header: 'Created',
            accessorFn: (row) => row.createdAt,
            enableSorting: sortable,
            sortDescFirst: true,
            enableMultiSort: false,
            meta: { sortDataAttr: 'release-all-sort-created' },
            cell: ({ row }) =>
                row.original.createdAt ? (
                    <Text size="xs" variant="muted" render={<span />} className="whitespace-nowrap">
                        <TZLabel time={row.original.createdAt} />
                    </Text>
                ) : (
                    <Text size="xs" variant="muted">
                        –
                    </Text>
                ),
        },
        {
            id: 'actions',
            enableResizing: false,
            header: '',
            enableSorting: false,
            meta: { align: 'right' },
            cell: ({ row }) => <ReleaseAllRowMenu row={row.original} />,
        },
    ]
}
