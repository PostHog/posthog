import { ReactNode } from 'react'

import { Table, TableBody, TableFooter, TableHeader, cn } from '@posthog/quill'

interface QuillDetailedResultsTableProps {
    header: ReactNode
    children: ReactNode
    footer?: ReactNode
    loading?: boolean
    'data-attr'?: string
}

export function QuillDetailedResultsTable({
    header,
    children,
    footer,
    loading,
    'data-attr': dataAttr,
}: QuillDetailedResultsTableProps): JSX.Element {
    return (
        <Table
            size="sm"
            // Sticky cells paint their own background, so they take the card color too.
            className="rounded-lg border bg-card [--quill-table-sticky-bg:var(--card)]"
            data-attr={dataAttr}
        >
            <TableHeader>{header}</TableHeader>
            <TableBody
                aria-busy={loading || undefined}
                className={cn('transition-opacity motion-reduce:transition-none', loading && 'opacity-50')}
            >
                {children}
            </TableBody>
            {footer && <TableFooter>{footer}</TableFooter>}
        </Table>
    )
}
