import { ArrowDown, ArrowUp, ChevronsUpDown } from 'lucide-react'
import { ReactNode } from 'react'

import { Button, cn } from '@posthog/quill'

import { Sorting } from 'lib/lemon-ui/LemonTable/sorting'

interface QuillColumnSortButtonProps {
    order: Sorting['order'] | null
    onClick: () => void
    children?: ReactNode
    'aria-label'?: string
}

// The same look as the sort button of quill's DataTable, which this table cannot use because its headers hold
// other controls, such as a checkbox or a pin button.
export function QuillColumnSortButton({
    order,
    onClick,
    children,
    'aria-label': ariaLabel,
}: QuillColumnSortButtonProps): JSX.Element {
    return (
        <Button
            size={children ? 'sm' : 'icon-sm'}
            aria-selected={order ? true : undefined}
            aria-label={ariaLabel}
            tooltip={children ? undefined : ariaLabel}
            className={cn(
                'max-w-72 gap-1.5 align-middle',
                !children && 'ml-2',
                order && 'text-foreground',
                !order && 'hover:bg-fill-hover/50'
            )}
            onClick={onClick}
        >
            {children && <span className="min-w-0 truncate">{children}</span>}
            {order === 1 ? (
                <ArrowUp className="size-3" />
            ) : order === -1 ? (
                <ArrowDown className="size-3" />
            ) : (
                <ChevronsUpDown className="size-3 opacity-50" />
            )}
        </Button>
    )
}
