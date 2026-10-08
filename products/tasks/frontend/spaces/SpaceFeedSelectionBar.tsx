import { useActions, useValues } from 'kea'

import { IconArchive, IconFolder, IconPin, IconPinFilled, IconX } from '@posthog/icons'
import {
    Button,
    Checkbox,
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuTrigger,
    Text,
    Tooltip,
    TooltipContent,
    TooltipTrigger,
} from '@posthog/quill'

import { TodaySessionBulkArchiveDialog } from '~/layout/today/TodaySessionBulkArchiveDialog'
import { sessionsLabel } from '~/layout/today/todaySessionSelection'
import { TodayBulkAction } from '~/layout/today/todaySessionSelectionLogic'
import { TodaySpaceFileList } from '~/layout/today/TodaySpaceFileList'
import { todaySpacesLogic } from '~/layout/today/todaySpacesLogic'

import { spaceFeedSelectionLogic } from './spaceFeedSelectionLogic'

const BUSY_REASON = 'Wait for the current change to finish'

interface BulkButtonProps {
    spaceId: string
    label: string
    action: TodayBulkAction
    icon: JSX.Element
    dataAttr: string
    onClick?: () => void
    /** Wraps the button before the tooltip does, so it can open a menu. */
    wrap?: (button: JSX.Element) => JSX.Element
}

function BulkButton({ spaceId, label, action, icon, dataAttr, onClick, wrap }: BulkButtonProps): JSX.Element {
    const { bulkAction } = useValues(spaceFeedSelectionLogic({ id: spaceId }))
    const loading = bulkAction === action
    const busy = bulkAction !== null && !loading
    const button = (
        <Button variant="outline" size="sm" loading={loading} disabled={busy} onClick={onClick} data-attr={dataAttr} />
    )
    return (
        <Tooltip disabled={!busy}>
            <TooltipTrigger delay={0} render={wrap ? wrap(button) : button}>
                {icon}
                {label}
            </TooltipTrigger>
            <TooltipContent>{BUSY_REASON}</TooltipContent>
        </Tooltip>
    )
}

/** Shows above the feed while sessions are picked, with the same bulk actions as the sidebar's selection bar. */
export function SpaceFeedSelectionBar({ spaceId }: { spaceId: string }): JSX.Element {
    const logic = spaceFeedSelectionLogic({ id: spaceId })
    const { selectedSessionIds, selectAll, bulkPinDirection, bulkArchiveConfirm, bulkAction } = useValues(logic)
    const {
        toggleSelectAll,
        pinSelected,
        fileSelectedTo,
        requestBulkArchive,
        clearSelection,
        closeBulkArchiveConfirm,
        archiveSelected,
    } = useActions(logic)
    const { spaces } = useValues(todaySpacesLogic)
    const count = selectedSessionIds.length
    const pin = bulkPinDirection === 'pin'

    return (
        <>
            {/* The bar unmounts with an empty selection, so the announcement lives outside it. */}
            <span aria-live="polite" className="sr-only">
                {count > 0 ? `${sessionsLabel(count)} selected` : ''}
            </span>
            {count > 0 && (
                // Early in the tab order, so the bulk actions are a few Tabs away; shown at the bottom of the feed.
                <div
                    className="sticky bottom-3 z-20 order-last mt-3 flex flex-wrap items-center gap-x-3 gap-y-1 max-w-full self-center rounded-lg border border-border bg-popover px-2 py-1.5 text-popover-foreground shadow-[var(--shadow-md)]"
                    data-attr="today-space-feed-bulk-bar"
                >
                    <div className="flex min-w-0 items-center gap-2">
                        <Checkbox
                            size="sm"
                            checked={selectAll === 'all'}
                            indeterminate={selectAll === 'some'}
                            onCheckedChange={toggleSelectAll}
                            aria-label="Select all sessions"
                            data-attr="today-space-feed-select-all"
                        />
                        <Text size="sm" weight="medium" render={<span />} className="shrink-0">
                            {`${count} selected`}
                        </Text>
                        <Text size="xs" variant="muted" render={<span />} className="truncate">
                            Esc to clear
                        </Text>
                    </div>
                    <div className="ml-auto flex flex-wrap items-center gap-1">
                        <BulkButton
                            spaceId={spaceId}
                            label={pin ? 'Pin' : 'Unpin'}
                            action="pin"
                            icon={pin ? <IconPin /> : <IconPinFilled />}
                            onClick={pinSelected}
                            dataAttr="today-space-feed-bulk-pin"
                        />
                        {spaces.length > 1 && (
                            <DropdownMenu>
                                <BulkButton
                                    spaceId={spaceId}
                                    label="File to…"
                                    action="file"
                                    icon={<IconFolder />}
                                    wrap={(button) => <DropdownMenuTrigger render={button} />}
                                    dataAttr="today-space-feed-bulk-file"
                                />
                                <DropdownMenuContent align="end" className="max-h-80 w-64">
                                    <TodaySpaceFileList
                                        currentSpaceId={spaceId}
                                        onSelect={fileSelectedTo}
                                        itemDataAttr="today-space-feed-bulk-file-space"
                                        searchDataAttr="today-space-feed-bulk-file-search"
                                    />
                                </DropdownMenuContent>
                            </DropdownMenu>
                        )}
                        <BulkButton
                            spaceId={spaceId}
                            label="Archive"
                            action="archive"
                            icon={<IconArchive />}
                            onClick={requestBulkArchive}
                            dataAttr="today-space-feed-bulk-archive"
                        />
                        <Tooltip>
                            <TooltipTrigger
                                delay={0}
                                render={
                                    <Button
                                        size="icon-sm"
                                        aria-label="Clear selection"
                                        onClick={clearSelection}
                                        data-attr="today-space-feed-bulk-clear"
                                    />
                                }
                            >
                                <IconX />
                            </TooltipTrigger>
                            <TooltipContent>Clear selection</TooltipContent>
                        </Tooltip>
                    </div>
                </div>
            )}
            <TodaySessionBulkArchiveDialog
                confirm={bulkArchiveConfirm}
                archiving={bulkAction === 'archive'}
                onCancel={closeBulkArchiveConfirm}
                onConfirm={archiveSelected}
                dataAttrPrefix="today-space-feed-bulk"
            />
        </>
    )
}
