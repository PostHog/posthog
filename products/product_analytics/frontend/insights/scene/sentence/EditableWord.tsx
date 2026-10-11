import { forwardRef } from 'react'

import { IconX } from '@posthog/icons'
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
    onRemove?: () => void
    removeLabel?: string
    'data-attr'?: string
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
    {
        className,
        color,
        lineColor,
        overridden,
        onRemove,
        removeLabel = 'Remove',
        'data-attr': dataAttr,
        children,
        ...props
    },
    ref
): JSX.Element {
    const word = (
        <button
            ref={ref}
            type="button"
            data-quill
            data-attr={dataAttr}
            className={cn(
                'inline cursor-pointer border-0 bg-transparent p-0 font-semibold underline-offset-4',
                'hover:underline aria-expanded:underline data-popup-open:underline',
                'focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring',
                className
            )}
            {...props}
        >
            {/* The app gives every mark element a pale yellow background, which is the resting wash here.
                Pale text is unreadable on it, so the dark theme swaps the yellow for a faint neutral wash. */}
            <span className={overridden ? 'relative inline-block' : undefined}>
                <Highlight
                    color={color}
                    className="not-hover:[--quill-highlight-background:transparent] dark:[--mark:color-mix(in_oklab,var(--foreground)_12%,transparent)]"
                    // eslint-disable-next-line react/forbid-dom-props
                    style={lineColor ? lineColorStyle(lineColor) : undefined}
                >
                    <span>{children}</span>
                </Highlight>
                {overridden && <DashboardFilterMark className="absolute -top-1 -right-3 rotate-12" />}
            </span>
        </button>
    )

    // The dashboard's mark has the same corner, and the saved insight cannot remove what the dashboard sets.
    if (!onRemove || overridden) {
        return word
    }

    return (
        <span className="group/word relative inline-block max-w-full">
            {word}
            <button
                type="button"
                data-quill
                aria-label={removeLabel}
                onClick={() => onRemove()}
                className={cn(
                    'absolute -top-1 -right-3 inline-flex size-4 cursor-pointer items-center justify-center rounded-full p-0',
                    'border border-(--border) bg-(--card) text-(--muted-foreground) shadow-(--shadow-sm)',
                    'opacity-0 transition-opacity group-hover/word:opacity-100 focus-visible:opacity-100',
                    'hover:border-transparent hover:bg-(--destructive) hover:text-(--destructive-foreground)',
                    'focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring'
                )}
                data-attr={dataAttr ? `${dataAttr}-remove` : undefined}
            >
                <IconX className="size-2.5" />
            </button>
        </span>
    )
})
