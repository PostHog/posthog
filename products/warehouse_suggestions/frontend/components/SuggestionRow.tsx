import { ReactNode } from 'react'

import { cn } from 'lib/utils/css-classes'

import type { SavingHighlight } from '../suggestionCopy'

export interface SuggestionRowProps {
    suggestionId: string
    icon: ReactNode
    title: ReactNode
    meta: ReactNode[]
    highlight?: SavingHighlight
    actions: ReactNode
    leaving: boolean
}

export function SuggestionRow({
    suggestionId,
    icon,
    title,
    meta,
    highlight,
    actions,
    leaving,
}: SuggestionRowProps): JSX.Element {
    return (
        <div
            data-suggestion-row={suggestionId}
            className={cn(
                'grid transition-[grid-template-rows,opacity] duration-150 ease-out motion-reduce:transition-none',
                leaving ? 'grid-rows-[0fr] opacity-0' : 'grid-rows-[1fr] opacity-100'
            )}
        >
            <div className="min-h-0 overflow-hidden">
                <div
                    className={cn(
                        'grid items-center gap-x-3 gap-y-1.5 px-3 py-2.5',
                        highlight
                            ? 'grid-cols-[minmax(0,1fr)_auto] @min-[36rem]/suggestions:grid-cols-[minmax(0,1fr)_10rem_minmax(15rem,auto)]'
                            : 'grid-cols-[minmax(0,1fr)_auto]'
                    )}
                >
                    <div
                        className={cn(
                            'flex min-w-0 items-start gap-2',
                            highlight && 'col-span-2 @min-[36rem]/suggestions:col-span-1'
                        )}
                    >
                        <span className="group/colorful-product-icons colorful-product-icons-true flex h-5 shrink-0 translate-y-0.5 items-center text-base">
                            {icon}
                        </span>
                        <div className="flex min-w-0 flex-col gap-0.5">
                            <div className="flex min-w-0">{title}</div>
                            <div className="flex flex-wrap items-center gap-x-1.5 gap-y-0.5 text-xs text-secondary">
                                {meta.map((item, index) => (
                                    <span key={index} className="inline-flex items-baseline gap-1.5">
                                        {index > 0 && (
                                            <span aria-hidden className="text-muted">
                                                ·
                                            </span>
                                        )}
                                        {item}
                                    </span>
                                ))}
                            </div>
                        </div>
                    </div>
                    {highlight && (
                        <div className="flex min-w-0 items-baseline gap-1.5 @min-[36rem]/suggestions:flex-col @min-[36rem]/suggestions:items-end @min-[36rem]/suggestions:gap-0">
                            <span translate="no" className="text-sm font-semibold tabular-nums text-success">
                                {highlight.amount}
                            </span>
                            <span className="text-xs text-secondary">{highlight.label}</span>
                        </div>
                    )}
                    <div data-suggestion-actions className="flex flex-wrap items-center justify-end gap-1">
                        {actions}
                    </div>
                </div>
            </div>
        </div>
    )
}
