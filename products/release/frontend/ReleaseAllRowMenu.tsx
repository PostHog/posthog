import { useActions, useValues } from 'kea'
import { useState } from 'react'

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

import { cn } from 'lib/utils/css-classes'
import { addProjectIdIfMissing } from 'lib/utils/kea-router'
import { navigateToHref } from 'lib/utils/navigateToHref'
import { newInternalTab } from 'lib/utils/newInternalTab'
import { writeToClipboard } from 'lib/utils/writeToClipboard'

import { SidebarPinHint } from '~/layout/today/sidebar/SidebarPinHint'
import { pinTargetKey, sidebarPinsLogic } from '~/layout/today/sidebar/sidebarPinsLogic'

import { releaseAllLogic, type ReleaseAllRow } from './releaseAllLogic'
import { releaseLogic } from './releaseLogic'

export function ReleaseAllRowMenu({ row }: { row: ReleaseAllRow }): JSX.Element {
    const { pinnedShortcutIds, shortcutDataLoading } = useValues(sidebarPinsLogic)
    const { togglePinned } = useActions(sidebarPinsLogic)
    // Read here, not passed in by the column factory: new columns would remount this cell and close its open menu.
    const { pinHintVisible } = useValues(releaseLogic)
    const { hidePinHint } = useActions(releaseLogic)
    const { displayRows } = useValues(releaseAllLogic)
    const pinHint = pinHintVisible && displayRows[0]?.type === row.type && displayRows[0]?.id === row.id
    const [trigger, setTrigger] = useState<HTMLButtonElement | null>(null)
    const target = { type: row.type, ref: row.id, name: row.name, href: row.href }
    const pinned = pinnedShortcutIds.has(pinTargetKey(target))

    const copyLink = async (): Promise<void> => {
        const outcome = await writeToClipboard(new URL(addProjectIdIfMissing(row.href), window.location.origin).href)
        if (trigger) {
            anchoredToast({
                description: outcome === 'copied' ? 'Link copied' : 'Couldn’t copy the link',
                anchor: trigger,
                side: 'left',
            })
        }
    }

    return (
        <DropdownMenu onOpenChange={(open) => open && pinHint && hidePinHint()}>
            {pinHint && trigger && (
                <SidebarPinHint anchor={trigger} onClose={hidePinHint} dataAttr="release-pin-hint" />
            )}
            <DropdownMenuTrigger
                render={
                    <Button
                        ref={setTrigger}
                        variant="default"
                        size="icon-sm"
                        aria-label={`Actions for ${row.name}`}
                        className={cn(pinHint && 'ring-2 ring-ring')}
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
