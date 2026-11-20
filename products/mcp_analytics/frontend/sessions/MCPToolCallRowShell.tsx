import { cn } from 'lib/utils/css-classes'

export function MCPToolCallRowShell({
    isError = false,
    focused = false,
    onClick,
    children,
}: {
    isError?: boolean
    focused?: boolean
    /** Makes the whole row clickable. Links and buttons inside it keep their own clicks. */
    onClick?: () => void
    children: React.ReactNode
}): JSX.Element {
    return (
        <li
            className={cn(
                'relative flex flex-col gap-1 rounded border border-l-2 bg-surface-primary px-2 py-1.5',
                isError ? 'border-danger' : 'border-primary border-l-accent/60',
                focused && 'ring-2 ring-accent',
                onClick && 'cursor-pointer hover:bg-fill-highlight-50'
            )}
            onClick={
                onClick &&
                ((event) => {
                    if (!(event.target as HTMLElement).closest('a, button')) {
                        onClick()
                    }
                })
            }
            onKeyDown={
                onClick &&
                ((event) => {
                    if (event.key === 'Enter' && event.target === event.currentTarget) {
                        onClick()
                    }
                })
            }
            tabIndex={onClick ? 0 : undefined}
            role={onClick ? 'button' : undefined}
        >
            {children}
        </li>
    )
}
