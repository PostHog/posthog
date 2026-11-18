import { Skeleton, Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@posthog/quill'

const COLUMNS: { id: string; label: string }[] = [
    { id: 'name', label: 'Title' },
    { id: 'status', label: 'Status' },
    { id: 'owner', label: 'Owner' },
    { id: 'created_at', label: 'Created' },
    { id: 'actions', label: '' },
]

export function ReleaseAllSkeleton(): JSX.Element {
    return (
        <div aria-busy aria-label="Loading releases" data-attr="release-all-loading">
            <Table fullWidth size="sm" className="**:data-expand:min-w-64 **:data-expand:max-w-0">
                <TableHeader>
                    <TableRow>
                        {COLUMNS.map((column) => (
                            <TableHead key={column.id} expand={column.id === 'name'}>
                                {column.label}
                            </TableHead>
                        ))}
                    </TableRow>
                </TableHeader>
                <TableBody aria-hidden>
                    {Array.from({ length: 8 }, (_, index) => (
                        <TableRow key={index}>
                            <TableCell expand>
                                <div className="flex h-6 min-w-48 items-center gap-2">
                                    <Skeleton className="size-4 shrink-0" />
                                    <Skeleton className={index % 2 === 0 ? 'h-3 w-40' : 'h-3 w-28'} />
                                </div>
                            </TableCell>
                            <TableCell>
                                <Skeleton className="h-3 w-16" />
                            </TableCell>
                            <TableCell>
                                <div className="flex w-28 items-center gap-2">
                                    <Skeleton className="size-5 shrink-0 rounded-full" />
                                    <Skeleton className="h-3 w-16" />
                                </div>
                            </TableCell>
                            <TableCell>
                                <Skeleton className="h-3 w-20" />
                            </TableCell>
                            <TableCell>
                                <div className="w-8" />
                            </TableCell>
                        </TableRow>
                    ))}
                </TableBody>
            </Table>
        </div>
    )
}
