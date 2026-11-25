import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { Tooltip } from '@posthog/lemon-ui'

import { LinkPrimitive } from 'lib/lemon-ui/Link'

import { captureInboxReportTagClicked } from '../../inboxAnalytics'
import { inboxFiltersLogic, inboxReportsUrlForTag } from '../../logics/inboxFiltersLogic'
import { SignalReport } from '../../types'
import { reportTagChipClassName } from './reportTagChipClassName'

const VISIBLE_TAG_LIMIT = 3

/**
 * A report's tags on the report page, styled like the tags on an inbox card. Each chip opens the
 * Reports list filtered to its tag alone. Tags in the Tags filter are highlighted and lead the row.
 * The `+n` chip shows the rest on hover and expands the row on a tap. List cards use the one-line
 * `ReportCardTagChips` instead, where a chip toggles its tag in the filter.
 */
export function ReportTagChips({ report }: { report: SignalReport }): JSX.Element | null {
    const { filterState } = useValues(inboxFiltersLogic)
    const { setTagFilter } = useActions(inboxFiltersLogic)
    const [expanded, setExpanded] = useState(false)
    const tags = report.tags ?? []
    if (tags.length === 0) {
        return null
    }

    const isSelected = (tag: string): boolean => filterState.tagFilter.includes(tag)
    const orderedTags = [...tags.filter(isSelected), ...tags.filter((tag) => !isSelected(tag))]
    const visible = expanded ? orderedTags : orderedTags.slice(0, VISIBLE_TAG_LIMIT)
    const hidden = orderedTags.slice(visible.length)

    return (
        // The negative margin lines the first tag's text up with the title above it.
        <div className="-mx-1 flex min-w-0 flex-wrap items-center gap-1" role="group" aria-label="Report tags">
            {visible.map((tag) => (
                <LinkPrimitive
                    key={tag}
                    to={inboxReportsUrlForTag(filterState, tag)}
                    title={`Show reports tagged ${tag}`}
                    onClick={() => {
                        // Set the filter before the link navigates. The Reports URL then matches the stored
                        // filters, so hydrating from it does not mark the scope and sort as chosen by the user.
                        setTagFilter([tag])
                        captureInboxReportTagClicked({ report, surface: 'detail', added: true, tagFilterCount: 1 })
                    }}
                    className={reportTagChipClassName(isSelected(tag))}
                    data-attr="inbox-report-tag"
                >
                    <span className="truncate">{`#${tag}`}</span>
                </LinkPrimitive>
            ))}
            {hidden.length > 0 && (
                <Tooltip title={hidden.join(', ')}>
                    <button
                        type="button"
                        aria-label={`Show ${hidden.length} more tags`}
                        onClick={() => setExpanded(true)}
                        className={clsx(reportTagChipClassName(false), 'shrink-0 cursor-pointer')}
                        data-attr="inbox-report-tag-overflow"
                    >
                        {`+${hidden.length}`}
                    </button>
                </Tooltip>
            )}
        </div>
    )
}
