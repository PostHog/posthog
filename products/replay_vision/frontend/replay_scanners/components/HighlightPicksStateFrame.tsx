import { ComponentType, ReactNode } from 'react'

import { cn } from 'lib/utils/css-classes'

interface HighlightPicksStateFrameProps {
    size: 'small' | 'large'
    image: ComponentType<{ className?: string }>
    title: ReactNode
    body: ReactNode
    children?: ReactNode
    footer?: ReactNode
    dataAttr: string
}

export function HighlightPicksStateFrame({
    size,
    image: Image,
    title,
    body,
    children,
    footer,
    dataAttr,
}: HighlightPicksStateFrameProps): JSX.Element {
    const large = size === 'large'
    return (
        <div
            className={cn(
                'flex flex-col items-center gap-2 text-center text-secondary',
                large ? 'rounded border bg-bg-light p-8 text-sm' : 'p-4 text-xs'
            )}
            data-attr={dataAttr}
        >
            <Image className={large ? 'h-48 w-48' : 'h-24 w-24'} />
            <span className={cn('font-semibold text-default', large ? 'text-lg' : 'text-sm')}>{title}</span>
            <span className="max-w-lg">{body}</span>
            {children && <div className="mt-1 flex w-full max-w-xs flex-col items-stretch gap-2">{children}</div>}
            {footer}
        </div>
    )
}
