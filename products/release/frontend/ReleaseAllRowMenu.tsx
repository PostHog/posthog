import { useActions, useValues } from 'kea'
import { useRef } from 'react'

import { IconArrowUpRight, IconCopy, IconEllipsis, IconExternal, IconPin, IconPinFilled } from '@posthog/icons'
import {
    Button,
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuGroup,
    DropdownMenuItem,
    DropdownMenuSeparator,
    DropdownMenuTrigger,
    anchoredToast,
} from '@posthog/quill'

import { addProjectIdIfMissing } from 'lib/utils/kea-router'
import { navigateToHref } from 'lib/utils/navigateToHref'
import { newInternalTab } from 'lib/utils/newInternalTab'
import { writeToClipboard } from 'lib/utils/writeToClipboard'

import { pinTargetKey, sidebarPinsLogic } from '~/layout/today/sidebar/sidebarPinsLogic'

import type { ReleaseAllRow } from './releaseAllLogic'

export function ReleaseAllRowMenu({ row }: { row: ReleaseAllRow }): JSX.Element {
    const { pinnedShortcutIds, shortcutDataLoading } = useValues(sidebarPinsLogic)
    const { togglePinned } = useActions(sidebarPinsLogic)
    const triggerRef = useRef<HTMLButtonElement>(null)
    const target = { type: row.type, ref: row.id, name: row.name, href: row.href }
    const pinned = pinnedShortcutIds.has(pinTargetKey(target))

    const copyLink = async (): Promise<void> => {
        const outcome = await writeToClipboard(new URL(addProjectIdIfMissing(row.href), window.location.origin).href)
        if (triggerRef.current) {
            anchoredToast({
                description: outcome === 'copied' ? 'Link copied' : 'Couldn’t copy the link',
                anchor: triggerRef.current,
                side: 'left',
            })
        }
    }

    return (
        <DropdownMenu>
            <DropdownMenuTrigger
                render={
                    <Button
                        ref={triggerRef}
                        variant="default"
                        size="icon-sm"
                        aria-label={`Actions for ${row.name}`}
                        data-attr="release-all-row-menu"
                    />
                }
            >
                <IconEllipsis />
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="min-w-48">
                <DropdownMenuGroup>
                    <DropdownMenuItem onClick={() => navigateToHref(row.href)} data-attr="release-all-row-view">
                        <IconArrowUpRight />
                        View
                    </DropdownMenuItem>
                    <DropdownMenuItem onClick={() => newInternalTab(row.href)} data-attr="release-all-row-new-tab">
                        <IconExternal />
                        Open in a new tab
                    </DropdownMenuItem>
                    <DropdownMenuItem onClick={() => void copyLink()} data-attr="release-all-row-copy-link">
                        <IconCopy />
                        Copy link
                    </DropdownMenuItem>
                </DropdownMenuGroup>
                <DropdownMenuSeparator />
                <DropdownMenuItem
                    disabledReason={shortcutDataLoading ? 'Loading your pinned items…' : undefined}
                    onClick={() => togglePinned(target)}
                    data-attr="release-all-row-pin"
                >
                    {pinned ? <IconPinFilled /> : <IconPin />}
                    {pinned ? 'Unpin from sidebar' : 'Pin to sidebar'}
                </DropdownMenuItem>
            </DropdownMenuContent>
        </DropdownMenu>
    )
}
