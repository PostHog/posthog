import { Fragment } from 'react'

import { Heading, ItemMenuItem, MenuLabel, ScrollArea, Separator, Skeleton, Text } from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'

export interface TodayRailPreviewItem {
    name: string
    href: string
    icon: JSX.Element
}

export function TodayRailPreviewList({
    title,
    pins,
    recents,
    loading = false,
    failed = false,
    onAction,
}: {
    title: string
    pins: TodayRailPreviewItem[]
    recents: TodayRailPreviewItem[]
    loading?: boolean
    failed?: boolean
    onAction: () => void
}): JSX.Element {
    const pinnedHrefs = new Set(pins.map((item) => item.href))
    const sections = [
        { label: 'Pinned', items: pins },
        { label: 'Recents', items: recents.filter((item) => !pinnedHrefs.has(item.href)) },
    ].filter((section) => section.items.length > 0)

    return (
        <div className="flex min-h-0 flex-col" data-attr="today-rail-hover-card">
            <Heading size="sm" className="px-3 py-3">
                {title}
            </Heading>
            {sections.length > 0 && (
                <>
                    <Separator />
                    <ScrollArea
                        className="min-h-0"
                        viewportClassName="max-h-96 max-h-[min(24rem,calc(var(--available-height,100vh)-4rem))] overscroll-contain"
                    >
                        <div className="p-1">
                            {sections.map((section, index) => (
                                <Fragment key={section.label}>
                                    {index > 0 && <Separator className="my-1" />}
                                    <MenuLabel>{section.label}</MenuLabel>
                                    <div role="group" aria-label={section.label} className="flex flex-col gap-px">
                                        {section.items.map((item) => (
                                            <ItemMenuItem
                                                key={item.href}
                                                role="link"
                                                className="flex-nowrap text-foreground"
                                                render={<LinkPrimitive to={item.href} />}
                                                onClickCapture={onAction}
                                                onAuxClick={(event) => event.button === 1 && onAction()}
                                                title={item.name}
                                                data-attr="today-rail-preview-item"
                                            >
                                                {item.icon}
                                                <span className="min-w-0 flex-1 truncate">{item.name}</span>
                                            </ItemMenuItem>
                                        ))}
                                    </div>
                                </Fragment>
                            ))}
                        </div>
                    </ScrollArea>
                </>
            )}
            {loading ? (
                <div role="status" aria-label="Loading items" className="flex flex-col gap-2 px-3 pb-3">
                    <Skeleton className="h-4 w-3/4" />
                    <Skeleton className="h-4 w-1/2" />
                </div>
            ) : failed ? (
                <Text size="xs" variant="muted" className="px-3 pb-3">
                    Some items could not load. Open Chats to try again.
                </Text>
            ) : null}
        </div>
    )
}
