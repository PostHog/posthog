import type { ReactNode } from 'react'

import { IconChevronRight } from '@posthog/icons'
import { LemonTag, type LemonTagType, Tooltip } from '@posthog/lemon-ui'

import { cn } from 'lib/utils/css-classes'

interface GoalRowTag {
    label: string
    type: LemonTagType
    tooltip?: string
}

function RowTag({ tag }: { tag: GoalRowTag }): JSX.Element {
    const element = (
        <LemonTag size="small" type={tag.type} className={cn('ms-2 align-[1px]', tag.tooltip && 'cursor-help')}>
            {tag.label}
        </LemonTag>
    )
    return tag.tooltip ? <Tooltip title={tag.tooltip}>{element}</Tooltip> : element
}

function TitleWithTag({ title, tag }: { title: string; tag: GoalRowTag }): JSX.Element {
    const split = title.lastIndexOf(' ')
    return (
        <>
            {title.slice(0, split + 1)}
            <span className="whitespace-nowrap">
                {title.slice(split + 1)}
                <RowTag tag={tag} />
            </span>
        </>
    )
}

export function GoalRow({
    icon,
    title,
    tag,
    body,
    facts,
    actions,
    expanded,
    onToggle,
    children,
    muted = false,
    dataAttr,
    id,
}: {
    icon: ReactNode
    title: ReactNode
    tag?: GoalRowTag
    body?: ReactNode
    facts?: ReactNode[]
    actions?: ReactNode
    expanded?: boolean
    onToggle?: () => void
    children?: ReactNode
    muted?: boolean
    dataAttr: string
    id?: string
}): JSX.Element {
    const shownFacts = (facts ?? []).filter(Boolean)
    const content = (
        <span className="flex min-w-0 flex-1 flex-col gap-1">
            <span className={cn('min-w-0 text-sm font-semibold leading-snug', muted && 'text-secondary')}>
                {tag && typeof title === 'string' ? (
                    <TitleWithTag title={title} tag={tag} />
                ) : (
                    <>
                        {title}
                        {tag && <RowTag tag={tag} />}
                    </>
                )}
            </span>
            {body}
            {shownFacts.length > 0 && (
                <span className="flex flex-wrap items-center gap-x-1.5 gap-y-0.5 text-xs leading-snug text-tertiary">
                    {shownFacts.map((fact, index) => (
                        <span key={index} className="flex items-center gap-x-1.5">
                            {index > 0 && <span aria-hidden>·</span>}
                            {fact}
                        </span>
                    ))}
                </span>
            )}
        </span>
    )
    return (
        <div
            className={cn(
                'flex scroll-mt-4 flex-col rounded border bg-surface-primary transition-colors',
                expanded ? 'border-secondary' : 'border-primary hover:border-secondary'
            )}
            data-attr={dataAttr}
            id={id}
        >
            <div className="flex min-w-0 items-start gap-3 px-3 py-2.5">
                {onToggle ? (
                    <button
                        type="button"
                        className="flex min-w-0 flex-1 cursor-pointer items-start gap-2 bg-transparent p-0 text-left text-inherit"
                        aria-expanded={!!expanded}
                        onClick={onToggle}
                        data-attr={`${dataAttr}-toggle`}
                    >
                        <IconChevronRight
                            className={cn(
                                'mt-0.5 size-4 shrink-0 text-tertiary transition-transform',
                                expanded && 'rotate-90'
                            )}
                        />
                        <span className="mt-0.5 flex shrink-0 text-secondary">{icon}</span>
                        {content}
                    </button>
                ) : (
                    <div className="flex min-w-0 flex-1 items-start gap-2">
                        <span className="mt-0.5 flex shrink-0 text-secondary">{icon}</span>
                        {content}
                    </div>
                )}
                {actions && <div className="flex shrink-0 items-center gap-1.5">{actions}</div>}
            </div>
            {expanded && children && (
                <div className="flex min-w-0 flex-col gap-3 border-t border-primary px-3 py-3 ps-15">{children}</div>
            )}
        </div>
    )
}
