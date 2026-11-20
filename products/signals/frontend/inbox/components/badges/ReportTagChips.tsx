import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { LemonTag, Tooltip } from '@posthog/lemon-ui'

import { captureInboxReportTagClicked, InboxReportTagSurface } from '../../inboxAnalytics'
import { INBOX_TAG_FILTER_MAX, inboxFiltersLogic } from '../../logics/inboxFiltersLogic'
import { SignalReport } from '../../types'

const VISIBLE_TAG_LIMIT = 3

/**
 * A report's tags as chips. Each chip adds its tag to the Tags filter or removes it. Tags in the
 * filter are highlighted and lead the row, so the tag a report matched on is never in the overflow.
 * The `+n` chip shows the rest on hover and expands the row on a tap.
 */
export function ReportTagChips({
    report,
    surface,
}: {
    report: SignalReport
    surface: InboxReportTagSurface
}): JSX.Element | null {
    const { tagFilter } = useValues(inboxFiltersLogic)
    const { toggleTag } = useActions(inboxFiltersLogic)
    const [expanded, setExpanded] = useState(false)
    const tags = report.tags ?? []
    if (tags.length === 0) {
        return null
    }

    const ordered = [
        ...tags.filter((tag) => tagFilter.includes(tag)),
        ...tags.filter((tag) => !tagFilter.includes(tag)),
    ]
    const visible = expanded ? ordered : ordered.slice(0, VISIBLE_TAG_LIMIT)
    const hidden = ordered.slice(visible.length)
    const filterFull = tagFilter.length >= INBOX_TAG_FILTER_MAX

    const onToggle = (tag: string): void => {
        const added = !tagFilter.includes(tag)
        toggleTag(tag)
        captureInboxReportTagClicked({
            report,
            surface,
            added,
            tagFilterCount: tagFilter.length + (added ? 1 : -1),
        })
    }

    return (
        <div className="flex min-w-0 flex-wrap items-center gap-1" role="group" aria-label="Report tags">
            {visible.map((tag) => {
                const selected = tagFilter.includes(tag)
                const disabled = !selected && filterFull
                return (
                    <button
                        key={tag}
                        type="button"
                        aria-pressed={selected}
                        disabled={disabled}
                        title={
                            disabled
                                ? `You can filter by up to ${INBOX_TAG_FILTER_MAX} tags`
                                : selected
                                  ? `Stop filtering by ${tag}`
                                  : `Show only reports tagged ${tag}`
                        }
                        onClick={() => onToggle(tag)}
                        className="min-w-0 max-w-full rounded disabled:cursor-not-allowed enabled:cursor-pointer"
                        data-attr="inbox-report-tag"
                    >
                        <LemonTag size="small" type={selected ? 'highlight' : 'muted'} className="max-w-full">
                            <span className="truncate">{tag}</span>
                        </LemonTag>
                    </button>
                )
            })}
            {hidden.length > 0 && (
                <Tooltip title={hidden.join(', ')}>
                    <button
                        type="button"
                        aria-label={`Show ${hidden.length} more tags`}
                        onClick={() => setExpanded(true)}
                        className="rounded cursor-pointer"
                        data-attr="inbox-report-tag-overflow"
                    >
                        <LemonTag size="small" type="muted">
                            +{hidden.length}
                        </LemonTag>
                    </button>
                </Tooltip>
            )}
        </div>
    )
}
