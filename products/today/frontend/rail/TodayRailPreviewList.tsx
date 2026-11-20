import { Button, Heading, ScrollArea, Skeleton, Text } from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'

import { sidebarRowClassName } from '~/layout/today/sidebar/SidebarOption'
import { SidebarRowIcon } from '~/layout/today/sidebar/SidebarRow'
import { TodayPaneGroupLabel } from '~/layout/today/TodayPaneGroupLabel'

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
        <div
            className="group/colorful-product-icons colorful-product-icons-true flex min-h-0 flex-col"
            data-attr="today-rail-hover-card"
        >
            <Heading size="sm" className="shrink-0 px-3 pt-2.5 pb-1" render={<h3 className="m-0" />}>
                {title}
            </Heading>
            {sections.length > 0 && (
                <ScrollArea
                    className="min-h-0"
                    viewportClassName="max-h-96 max-h-[min(24rem,calc(var(--available-height,100vh)-4rem))] overscroll-contain"
                >
                    <div className="px-1 pb-1">
                        {sections.map((section, index) => (
                            <div key={section.label} role="group" aria-label={section.label}>
                                <TodayPaneGroupLabel first={index === 0}>{section.label}</TodayPaneGroupLabel>
                                <div className="flex flex-col gap-px">
                                    {section.items.map((item) => (
                                        <Button
                                            key={item.href}
                                            size="row"
                                            left
                                            nativeButton={false}
                                            render={<LinkPrimitive to={item.href} />}
                                            className={sidebarRowClassName('default')}
                                            onClickCapture={onAction}
                                            onAuxClick={(event) => event.button === 1 && onAction()}
                                            title={item.name}
                                            data-attr="today-rail-preview-item"
                                        >
                                            <span className="flex min-w-0 items-center gap-1.5">
                                                <SidebarRowIcon icon={item.icon} />
                                                <span className="min-w-0 flex-1 truncate">{item.name}</span>
                                            </span>
                                        </Button>
                                    ))}
                                </div>
                            </div>
                        ))}
                    </div>
                </ScrollArea>
            )}
            {loading ? (
                <div role="status" aria-label="Loading items" className="flex flex-col gap-2 px-3 pt-1 pb-3">
                    <Skeleton className="h-4 w-3/4" />
                    <Skeleton className="h-4 w-1/2" />
                </div>
            ) : failed ? (
                <Text size="xs" variant="muted" className="px-3 pt-1 pb-3">
                    Some items could not load. Open Chats to try again.
                </Text>
            ) : sections.length === 0 ? (
                <Text size="xs" variant="muted" className="px-3 pt-1 pb-3">
                    Items you pin or open show here.
                </Text>
            ) : null}
        </div>
    )
}
