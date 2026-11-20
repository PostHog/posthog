import { useActions } from 'kea'
import { useEffect, useRef } from 'react'

import { Button, Heading, ScrollArea, Skeleton, Text } from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'

import { sidebarRowClassName } from '~/layout/today/sidebar/SidebarOption'
import { SidebarRowIcon } from '~/layout/today/sidebar/SidebarRow'
import { TodayPaneGroupLabel } from '~/layout/today/TodayPaneGroupLabel'
import { TodayRailPane, todayShellLogic } from '~/layout/today/todayShellLogic'

import { todayRailCardLogic } from './todayRailCardLogic'

export interface TodayRailPreviewItem {
    name: string
    href: string
    icon: JSX.Element
}

export function TodayRailPreviewList({
    pane,
    title,
    pins,
    recents,
    loading = false,
    failed = false,
    onAction,
}: {
    pane: TodayRailPane
    title: string
    pins: TodayRailPreviewItem[]
    recents: TodayRailPreviewItem[]
    loading?: boolean
    failed?: boolean
    onAction: () => void
}): JSX.Element | null {
    const { setPickedPane } = useActions(todayShellLogic)
    const { cardShown, itemOpened } = useActions(todayRailCardLogic)
    const pinnedHrefs = new Set(pins.map((item) => item.href))
    const unpinnedRecents = recents.filter((item) => !pinnedHrefs.has(item.href))
    const sections = [
        { key: 'recents' as const, label: 'Recents', items: unpinnedRecents },
        { key: 'pinned' as const, label: 'Pinned', items: pins },
    ].filter((section) => section.items.length > 0)
    const shownFor = useRef<TodayRailPane | null>(null)

    useEffect(() => {
        if (!loading && unpinnedRecents.length + pins.length > 0 && shownFor.current !== pane) {
            shownFor.current = pane
            cardShown(pane, unpinnedRecents.length, pins.length)
        }
    }, [pane, loading, unpinnedRecents.length, pins.length, cardShown])

    if (sections.length === 0 && !loading && !failed) {
        return null
    }

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
                    viewportClassName="max-h-[min(20rem,calc(var(--available-height,20rem)-3rem))] overscroll-contain"
                >
                    <div className="px-1 pb-1">
                        {sections.map((section, index) => (
                            <div key={section.key} role="group" aria-label={section.label}>
                                <TodayPaneGroupLabel first={index === 0}>{section.label}</TodayPaneGroupLabel>
                                <div className="flex flex-col gap-px">
                                    {section.items.map((item, position) => (
                                        <Button
                                            key={item.href}
                                            size="row"
                                            left
                                            nativeButton={false}
                                            render={<LinkPrimitive to={item.href} />}
                                            className={sidebarRowClassName('default')}
                                            onClickCapture={(event) => {
                                                itemOpened(
                                                    pane,
                                                    section.key,
                                                    position,
                                                    event.metaKey || event.ctrlKey || event.shiftKey
                                                )
                                                onAction()
                                            }}
                                            onClick={() => setPickedPane(pane)}
                                            onAuxClick={(event) => {
                                                if (event.button === 1) {
                                                    itemOpened(pane, section.key, position, true)
                                                    onAction()
                                                }
                                            }}
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
            ) : null}
        </div>
    )
}
