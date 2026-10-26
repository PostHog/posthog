import { ReactNode } from 'react'

import { cn } from 'lib/utils/css-classes'

import { COMBINED_SAVING_LABEL, SavingHighlight } from '../suggestionCopy'

const AMOUNT_CLASS = 'text-sm font-semibold tabular-nums text-success'

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
                        'grid grid-cols-1 gap-y-2 px-3 py-2.5 @min-[36rem]/suggestions:items-center @min-[36rem]/suggestions:gap-x-3',
                        highlight
                            ? '@min-[36rem]/suggestions:grid-cols-[minmax(0,1fr)_10rem_minmax(15rem,auto)]'
                            : '@min-[36rem]/suggestions:grid-cols-[minmax(0,1fr)_auto]'
                    )}
                >
                    <div className="flex min-w-0 items-start gap-2">
                        <span className="group/colorful-product-icons colorful-product-icons-true flex h-5 shrink-0 translate-y-0.5 items-center text-base">
                            {icon}
                        </span>
                        <div className="flex min-w-0 flex-col gap-0.5">
                            <div className="flex min-w-0">{title}</div>
                            {highlight && (
                                <div className="flex flex-wrap items-baseline gap-x-1.5 @min-[36rem]/suggestions:hidden">
                                    <span translate="no" className={AMOUNT_CLASS}>
                                        {highlight.amount}
                                    </span>
                                    {highlight.bytes && (
                                        <>
                                            <span aria-hidden className="text-muted">
                                                ·
                                            </span>
                                            <span translate="no" className={AMOUNT_CLASS}>
                                                {highlight.bytes.amount}
                                            </span>
                                        </>
                                    )}
                                    <span className="text-xs text-secondary">
                                        {highlight.bytes ? COMBINED_SAVING_LABEL : highlight.label}
                                    </span>
                                </div>
                            )}
                            <div className="flex flex-wrap items-baseline gap-x-4 gap-y-0.5 overflow-hidden text-xs text-secondary">
                                {meta.map((item, index) => (
                                    <span key={index} className="-ml-4 inline-flex items-baseline">
                                        <span aria-hidden className="w-4 shrink-0 text-center text-muted">
                                            ·
                                        </span>
                                        {item}
                                    </span>
                                ))}
                            </div>
                        </div>
                    </div>
                    {highlight && (
                        <div className="hidden min-w-0 flex-col items-end @min-[36rem]/suggestions:flex">
                            <span translate="no" className={AMOUNT_CLASS}>
                                {highlight.amount}
                            </span>
                            <span className="text-xs text-secondary">{highlight.label}</span>
                            {highlight.bytes && (
                                <span translate="no" className="text-xs tabular-nums text-secondary">
                                    {`${highlight.bytes.amount} ${highlight.bytes.label}`}
                                </span>
                            )}
                        </div>
                    )}
                    <div
                        data-suggestion-actions
                        className="flex flex-wrap items-center gap-1 pl-6 @min-[36rem]/suggestions:justify-end @min-[36rem]/suggestions:pl-0"
                    >
                        {actions}
                    </div>
                </div>
            </div>
        </div>
    )
}
