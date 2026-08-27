import { BindLogic, useActions, useValues } from 'kea'
import { JSX, useEffect } from 'react'

import { IconChevronDown } from '@posthog/icons'
import { LemonButton, LemonSkeleton, LemonTag } from '@posthog/lemon-ui'

import { cn } from 'lib/utils/css-classes'

import { inboxReportSectionsLogic } from '../logics/inboxReportSectionsLogic'
import { INBOX_REPORT_SECTION_LIST_PARAMS, reportListLogic } from '../logics/reportListLogic'
import {
    INBOX_REPORT_SECTION_DESCRIPTION,
    INBOX_REPORT_SECTION_LABEL,
    INBOX_REPORT_SECTION_TAG,
    InboxReportSectionKey,
} from '../types'
import { CardSkeleton } from './cards/CardSkeleton'
import { ReportCard } from './cards/ReportCard'
import { useReportImpressions } from './useReportImpressions'

/** Copy shown in place of the rows when a section matches nothing. */
const EMPTY_SECTION_COPY: Record<InboxReportSectionKey, string> = {
    'needs-decision': 'No reports are waiting for a pull request.',
    monitoring: 'No pull requests open yet. Start one from a report above.',
    resolved: 'Nothing resolved or archived yet.',
    'not-actionable': 'Nothing has been judged not actionable.',
}

/**
 * One section of the Reports list: a collapsible run of report cards over its own filtered request.
 * The header carries the section's count whether or not it is expanded, so a collapsed section still
 * says how much is behind it; the rows themselves only load once it opens.
 */
export function InboxReportSection({ sectionKey }: { sectionKey: InboxReportSectionKey }): JSX.Element {
    return (
        <BindLogic
            logic={reportListLogic}
            props={{ sectionKey, listParams: INBOX_REPORT_SECTION_LIST_PARAMS[sectionKey] }}
        >
            <section className="flex flex-col gap-2">
                <SectionHeader sectionKey={sectionKey} />
                <SectionBody sectionKey={sectionKey} />
            </section>
        </BindLogic>
    )
}

function SectionHeader({ sectionKey }: { sectionKey: InboxReportSectionKey }): JSX.Element {
    const { count, countLoading } = useValues(reportListLogic)
    const { openSections } = useValues(inboxReportSectionsLogic)
    const { toggleSection } = useActions(inboxReportSectionsLogic)
    const isOpen = openSections[sectionKey]
    const tag = INBOX_REPORT_SECTION_TAG[sectionKey]

    return (
        <button
            type="button"
            className="flex w-full cursor-pointer items-center gap-2 rounded px-0.5 py-1 text-left"
            onClick={() => toggleSection(sectionKey)}
            aria-expanded={isOpen}
            title={INBOX_REPORT_SECTION_DESCRIPTION[sectionKey]}
            data-attr={`inbox-report-section-${sectionKey}`}
        >
            <span className="flex items-center gap-1 font-mono text-[11px] font-semibold uppercase tracking-widest text-secondary">
                {INBOX_REPORT_SECTION_LABEL[sectionKey]}
                {/* Skeleton only while the request is genuinely in flight; on failure `count` stays
                    null, so fall back to the number (0) rather than a permanent skeleton. */}
                {count === null && countLoading ? (
                    <LemonSkeleton className="h-3 w-4 rounded" />
                ) : (
                    <span className="tabular-nums">({count ?? 0})</span>
                )}
            </span>
            {tag && (
                <LemonTag type="completion" size="small">
                    {tag}
                </LemonTag>
            )}
            <div className="h-px flex-1 bg-border-primary" />
            <IconChevronDown className={cn('text-tertiary transition-transform', isOpen && 'rotate-180')} />
        </button>
    )
}

function SectionBody({ sectionKey }: { sectionKey: InboxReportSectionKey }): JSX.Element | null {
    const { visibleReports, hiddenReportCount, count, isLoaded, reportsLoadFailed, reportsResponseLoading } =
        useValues(reportListLogic)
    const { ensureLoaded, showMore, restoreReport } = useActions(reportListLogic)
    const { openSections } = useValues(inboxReportSectionsLogic)
    const isOpen = openSections[sectionKey]

    useReportImpressions(sectionKey, isOpen)

    // Rows are fetched on first expand, not on mount — a collapsed section costs one count request.
    useEffect(() => {
        if (isOpen) {
            ensureLoaded()
        }
    }, [isOpen, ensureLoaded])

    if (!isOpen) {
        return null
    }
    // The first fetch failed: kea loaders keep the response null, so `isLoaded` never flips. Show a
    // retry instead of a skeleton that would otherwise spin forever with no way to recover.
    if (!isLoaded && reportsLoadFailed) {
        return (
            <div className="flex flex-col items-start gap-2 px-1 py-2">
                <p className="m-0 text-sm text-tertiary">Couldn't load these reports.</p>
                <LemonButton
                    size="small"
                    type="secondary"
                    onClick={() => ensureLoaded()}
                    data-attr={`inbox-report-section-retry-${sectionKey}`}
                >
                    Retry
                </LemonButton>
            </div>
        )
    }
    // Loading, then empty, then content: `reports` is empty during the first fetch too, and a
    // section that is about to show ten rows must not flash "nothing here" on the way.
    if (!isLoaded) {
        return <CardSkeleton count={Math.min(count || 3, 5)} variant="cards" dashed={sectionKey !== 'monitoring'} />
    }
    if (visibleReports.length === 0) {
        return <p className="px-1 py-2 text-sm text-tertiary">{EMPTY_SECTION_COPY[sectionKey]}</p>
    }

    return (
        <div className="flex flex-col gap-1.5">
            {visibleReports.map((report) => (
                <ReportCard
                    key={report.id}
                    report={report}
                    sectionKey={sectionKey}
                    onRestore={() => restoreReport(report.id)}
                />
            ))}
            {hiddenReportCount > 0 && (
                <div className="flex justify-center pt-1">
                    <LemonButton
                        size="small"
                        type="tertiary"
                        onClick={showMore}
                        loading={reportsResponseLoading}
                        disabledReason={reportsResponseLoading ? 'Loading more reports' : undefined}
                        data-attr={`inbox-report-section-show-more-${sectionKey}`}
                    >
                        Show more ({hiddenReportCount})
                    </LemonButton>
                </div>
            )}
        </div>
    )
}
