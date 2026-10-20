import { cn } from 'lib/utils/css-classes'

export function TileBadge({
    children,
    placement,
    color,
    size = 'default',
}: {
    children: React.ReactNode
    placement: 'count' | 'setting'
    color?: string
    size?: 'default' | 'mini'
}): JSX.Element {
    return (
        <span
            className={cn(
                'pointer-events-none absolute z-[2] whitespace-nowrap rounded-full border bg-surface-primary font-semibold',
                size === 'mini' ? 'px-1 text-[9.5px] leading-[14px]' : 'px-1.5 text-[11px] leading-[18px] shadow-sm',
                placement === 'count'
                    ? size === 'mini'
                        ? '-right-2.5 -top-2'
                        : '-right-3 -top-2.5'
                    : size === 'mini'
                      ? 'left-1/2 top-full mt-0.5 -translate-x-1/2'
                      : '-bottom-2 left-1/2 -translate-x-1/2'
            )}
            style={color ? { color } : undefined}
            translate="no"
        >
            {children}
        </span>
    )
}
