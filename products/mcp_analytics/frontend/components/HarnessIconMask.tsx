import { type CSSProperties } from 'react'

import { cn } from 'lib/utils/css-classes'

// `src` must be a validated data URI: other text inside url() could add a mask layer that loads a remote image.
export function HarnessIconMask({
    src,
    label,
    className = 'size-4',
}: {
    src: string
    label?: string
    className?: string
}): JSX.Element {
    const a11y = label ? ({ role: 'img', 'aria-label': label } as const) : ({ 'aria-hidden': true } as const)
    // Tailwind classes are static, so the per-harness image reaches the mask through a CSS variable.
    const style = { '--harness-icon': `url("${src}")` } as CSSProperties
    return (
        <span
            {...a11y}
            title={label}
            className={cn(
                'inline-block shrink-0 bg-current mask-(--harness-icon) mask-contain mask-no-repeat mask-center',
                className
            )}
            // eslint-disable-next-line react/forbid-dom-props
            style={style}
        />
    )
}
