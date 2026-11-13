import { ReactNode } from 'react'

import { Tooltip, TooltipContent, TooltipTrigger, cn } from '@posthog/quill'

import { SavingHighlight } from '../suggestionCopy'
import { QuillSuggestionAssigneeSelect } from './QuillSuggestionAssigneeSelect'
import { SuggestionRowProps } from './SuggestionRow'

export interface QuillRowSelectionProps {
    selection?: ReactNode
}

export const QUILL_SAVING_COLUMNS_CLASS =
    '@min-[36rem]/suggestions:grid-cols-[minmax(0,1fr)_10rem_11rem] @min-[36rem]/suggestions:gap-x-3'

const AMOUNT_CLASS = 'text-sm font-semibold tabular-nums text-success-foreground'

function QuillHighlightAmount({ highlight }: { highlight: SavingHighlight }): JSX.Element {
    const amount = (
        <span translate="no" className={AMOUNT_CLASS}>
            {highlight.amount}
        </span>
    )
    if (!highlight.tooltip?.length) {
        return amount
    }
    return (
        <Tooltip>
            <TooltipTrigger
                render={<span tabIndex={0} className="cursor-help underline decoration-dotted underline-offset-2" />}
            >
                {amount}
            </TooltipTrigger>
            <TooltipContent>
                <span className="flex flex-col gap-0.5">
                    {highlight.tooltip.map((line) => (
                        <span key={line}>{line}</span>
                    ))}
                </span>
            </TooltipContent>
        </Tooltip>
    )
}

export function QuillSuggestionRow({
    suggestionId,
    assignee,
    canAct,
    icon,
    title,
    meta,
    highlight,
    actions,
    leaving,
    selection,
}: SuggestionRowProps & QuillRowSelectionProps): JSX.Element {
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
                            ? QUILL_SAVING_COLUMNS_CLASS
                            : '@min-[36rem]/suggestions:grid-cols-[minmax(0,1fr)_auto]'
                    )}
                >
                    <div className="flex min-w-0 items-start gap-2">
                        {selection && (
                            <span className="flex h-5 shrink-0 translate-y-0.5 items-center">{selection}</span>
                        )}
                        <span className="group/colorful-product-icons colorful-product-icons-true flex h-5 shrink-0 translate-y-0.5 items-center text-base">
                            {icon}
                        </span>
                        <div className="flex min-w-0 flex-col gap-0.5">
                            <div className="flex min-w-0">{title}</div>
                            {highlight && (
                                <div className="flex flex-wrap items-baseline gap-x-1.5 @min-[36rem]/suggestions:hidden">
                                    <QuillHighlightAmount highlight={highlight} />
                                    <span className="text-xs text-muted-foreground">{highlight.narrowLabel}</span>
                                </div>
                            )}
                            <div className="flex flex-wrap items-baseline gap-x-4 gap-y-0.5 overflow-hidden text-xs text-muted-foreground">
                                {[
                                    ...meta,
                                    <QuillSuggestionAssigneeSelect
                                        key="assignee"
                                        suggestionId={suggestionId}
                                        assignee={assignee}
                                        canAct={canAct}
                                    />,
                                ].map((item, index) => (
                                    <span key={index} className="-ml-4 inline-flex items-baseline">
                                        <span aria-hidden className="w-4 shrink-0 text-center text-subtle-foreground">
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
                            <QuillHighlightAmount highlight={highlight} />
                            {highlight.detail && (
                                <span translate="no" className="text-xs tabular-nums text-muted-foreground">
                                    {highlight.detail}
                                </span>
                            )}
                        </div>
                    )}
                    <div
                        data-suggestion-actions
                        className={cn(
                            'flex flex-wrap items-center gap-1 @min-[36rem]/suggestions:justify-end @min-[36rem]/suggestions:pl-0',
                            selection ? 'pl-12' : 'pl-6'
                        )}
                    >
                        {actions}
                    </div>
                </div>
            </div>
        </div>
    )
}
