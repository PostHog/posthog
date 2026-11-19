import { cn } from 'lib/utils/css-classes'

export function MCPToolCallRowShell({
    isError = false,
    children,
}: {
    isError?: boolean
    children: React.ReactNode
}): JSX.Element {
    return (
        <li
            className={cn(
                'relative flex flex-col gap-1 rounded border border-l-2 bg-surface-primary px-2 py-1.5',
                isError ? 'border-danger' : 'border-primary border-l-accent/60'
            )}
        >
            {children}
        </li>
    )
}
