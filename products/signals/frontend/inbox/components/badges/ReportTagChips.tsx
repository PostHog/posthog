import { useState } from 'react'

import { LemonTag, Tooltip } from '@posthog/lemon-ui'

import { InboxReportTagSurface } from '../../inboxAnalytics'
import { SignalReport } from '../../types'
import { useReportTagToggle } from './useReportTagToggle'

const VISIBLE_TAG_LIMIT = 3

/**
 * A report's tags as chips. Each chip adds its tag to the Tags filter or removes it. Tags in the
 * filter are highlighted and lead the row, so the tag a report matched on is never in the overflow.
 * The `+n` chip shows the rest on hover and expands the row on a tap. List cards use the one-line
 * `ReportCardTagChips` instead.
 */
export function ReportTagChips({
    report,
    surface,
}: {
    report: SignalReport
    surface: InboxReportTagSurface
}): JSX.Element | null {
    const { orderedTags, isSelected, isDisabled, title, toggle } = useReportTagToggle(report, surface)
    const [expanded, setExpanded] = useState(false)
    if (orderedTags.length === 0) {
        return null
    }

    const visible = expanded ? orderedTags : orderedTags.slice(0, VISIBLE_TAG_LIMIT)
    const hidden = orderedTags.slice(visible.length)

    return (
        <div className="flex min-w-0 flex-wrap items-center gap-1" role="group" aria-label="Report tags">
            {visible.map((tag) => {
                const selected = isSelected(tag)
                return (
                    <button
                        key={tag}
                        type="button"
                        aria-pressed={selected}
                        disabled={isDisabled(tag)}
                        title={title(tag)}
                        onClick={() => toggle(tag)}
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
