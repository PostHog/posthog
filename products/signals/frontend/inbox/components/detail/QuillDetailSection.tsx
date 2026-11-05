import { ReactNode, useState } from 'react'

import { Collapsible, CollapsibleContent, CollapsibleTrigger, Text } from '@posthog/quill'

interface QuillDetailSectionProps {
    icon: ReactNode
    title: string
    /** Metadata right after the title, such as a branch tag or an info icon. */
    afterTitle?: ReactNode
    /** Non-interactive summary at the end of the header row. Part of the toggle when the section collapses. */
    meta?: ReactNode | ((open: boolean) => ReactNode)
    /** Summary below the header. A render function can adapt it to the section state. */
    summary?: ReactNode | ((open: boolean) => ReactNode)
    /** Controls outside the toggle, so their own clicks still work. */
    rightSlot?: ReactNode
    children: ReactNode
    collapsible?: boolean
    defaultCollapsed?: boolean
    onToggleCollapsed?: (collapsed: boolean) => void
}

/** The quill sibling of `DetailSection`, for the report page behind `today-rail-nav`. Same props, same behavior. */
export function QuillDetailSection({
    icon,
    title,
    afterTitle,
    meta,
    summary,
    rightSlot,
    children,
    collapsible = false,
    defaultCollapsed = false,
    onToggleCollapsed,
}: QuillDetailSectionProps): JSX.Element {
    const [collapsed, setCollapsed] = useState(collapsible && defaultCollapsed)
    const open = !collapsed
    const renderedMeta = typeof meta === 'function' ? meta(open) : meta
    const renderedSummary = typeof summary === 'function' ? summary(open) : summary

    const headerRow = (
        <span className="flex min-w-0 flex-1 items-center gap-2">
            <span className="flex shrink-0 items-center text-muted-foreground [&_svg]:size-4">{icon}</span>
            <Text size="sm" weight="semibold" render={<span />} className="truncate">
                {title}
            </Text>
            {afterTitle && <span className="shrink-0">{afterTitle}</span>}
            {renderedMeta && <span className="ms-auto shrink-0">{renderedMeta}</span>}
        </span>
    )

    return (
        <Collapsible
            open={open}
            onOpenChange={(nextOpen) => {
                setCollapsed(!nextOpen)
                onToggleCollapsed?.(!nextOpen)
            }}
            className="flex flex-col gap-2"
        >
            <div className="flex min-w-0 items-center gap-2">
                {collapsible ? (
                    <CollapsibleTrigger className="-ms-2 min-w-0 flex-1">{headerRow}</CollapsibleTrigger>
                ) : (
                    <div className="flex min-w-0 flex-1 items-center py-1">{headerRow}</div>
                )}
                {rightSlot && <div className="shrink-0">{rightSlot}</div>}
            </div>
            {renderedSummary && <div className="min-w-0">{renderedSummary}</div>}
            {collapsible ? <CollapsibleContent>{children}</CollapsibleContent> : <div>{children}</div>}
        </Collapsible>
    )
}
