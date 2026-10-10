import { forwardRef } from 'react'

import { Highlight, cn } from '@posthog/quill'
import type { HighlightColor } from '@posthog/quill'

import { DashboardFilterMark } from './DashboardFilterMark'

export interface EditableWordProps extends Omit<React.ComponentPropsWithoutRef<'button'>, 'color'> {
    /** The part of the question this word answers. Words with the same role share a color. */
    color: HighlightColor
    /** The color of the chart line this word stands for. It replaces the role color, so the word reads as a legend. */
    lineColor?: string
    /** A dashboard's filters set this word, not the saved insight. */
    overridden?: boolean
}

// A data color arrives as a value and not a token. Mixing it with the foreground keeps a pale line color readable as text.
function lineColorStyle(lineColor: string): React.CSSProperties {
    return {
        '--quill-highlight-foreground': `color-mix(in oklab, ${lineColor} 80%, var(--foreground))`,
        '--quill-highlight-background': `color-mix(in oklab, ${lineColor} 18%, transparent)`,
    } as React.CSSProperties
}

/** An editable word inside the sentence. Quill has no inline text trigger, so this wraps its highlight in a button. */
export const EditableWord = forwardRef<HTMLButtonElement, EditableWordProps>(function EditableWord(
    { className, color, lineColor, overridden, children, ...props },
    ref
): JSX.Element {
    return (
        <button
            ref={ref}
            type="button"
            data-quill
            className={cn(
                'inline cursor-pointer border-0 bg-transparent p-0 font-semibold underline-offset-4',
                'hover:underline aria-expanded:underline data-popup-open:underline',
                'focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring',
                className
            )}
            {...props}
        >
            {/* The app gives every mark element a pale yellow background, which is the resting wash here. */}
            <span className={overridden ? 'relative inline-block' : undefined}>
                <Highlight
                    color={color}
                    className="not-hover:[--quill-highlight-background:transparent]"
                    // eslint-disable-next-line react/forbid-dom-props
                    style={lineColor ? lineColorStyle(lineColor) : undefined}
                >
                    <span>{children}</span>
                </Highlight>
                {overridden && <DashboardFilterMark className="absolute -top-1 -right-3 rotate-12" />}
            </span>
        </button>
    )
})
