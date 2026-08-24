import { useActions, useValues } from 'kea'
import { JSX, useEffect, useRef } from 'react'

import { IconNotebook } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { KeyboardShortcut } from 'lib/components/KeyboardShortcut/KeyboardShortcut'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { urls } from 'scenes/urls'

import { captureInboxViewed } from '../../inboxAnalytics'
import { inboxSceneLogic } from '../../inboxSceneLogic'
import { inboxFiltersLogic } from '../../logics/inboxFiltersLogic'
import { INBOX_REPORT_SECTION_LIST_PARAMS, reportListLogic } from '../../logics/reportListLogic'
import {
    INBOX_REPORT_SECTION_KEYS,
    INBOX_STAFF_ONLY_REPORT_SECTION_KEYS,
    InboxReportSectionKey,
    SignalReport,
} from '../../types'
import { InboxWaitingForWork } from '../emptyState/InboxWaitingForWork'
import { InboxReportSection } from '../InboxReportSection'
import { SelfDrivingInstallingHint } from '../SelfDrivingInstallingHint'
import { InboxBulkSelectionBar } from '../shell/InboxBulkSelectionBar'
import { InboxSearchFilterBar } from '../shell/InboxSearchFilterBar'

/**
 * The sections that make up "the inbox" for counting purposes. Not actionable is left out: it is a
 * staff triage surface, and counting it would make the inbox look non-empty to staff on a project
 * that has surfaced nothing worth acting on. A fixed list, so the hooks below never change shape
 * when the user's staff flag resolves.
 */
const COUNTED_SECTION_KEYS = ['needs-decision', 'monitoring', 'resolved'] as const

type CountedSectionKey = (typeof COUNTED_SECTION_KEYS)[number]

interface SectionListState {
    count: number | null
    countLoading: boolean
    visibleReports: SignalReport[]
    refresh: () => void
}

/**
 * Each counted section's header count, rendered rows, and refresh action, keyed by section.
 *
 * Read one value at a time rather than spreading what `useValues` returns: it hands back a proxy
 * whose properties are subscribing getters, and spreading it yields an empty object — silently, and
 * with a type that still claims every value is there.
 */
function useCountedSections(): Record<CountedSectionKey, SectionListState> {
    const needsDecisionProps = {
        sectionKey: 'needs-decision' as const,
        listParams: INBOX_REPORT_SECTION_LIST_PARAMS['needs-decision'],
    }
    const monitoringProps = {
        sectionKey: 'monitoring' as const,
        listParams: INBOX_REPORT_SECTION_LIST_PARAMS.monitoring,
    }
    const resolvedProps = { sectionKey: 'resolved' as const, listParams: INBOX_REPORT_SECTION_LIST_PARAMS.resolved }

    const {
        count: needsDecisionCount,
        countLoading: needsDecisionCountLoading,
        visibleReports: needsDecisionReports,
    } = useValues(reportListLogic(needsDecisionProps))
    const {
        count: monitoringCount,
        countLoading: monitoringCountLoading,
        visibleReports: monitoringReports,
    } = useValues(reportListLogic(monitoringProps))
    const {
        count: resolvedCount,
        countLoading: resolvedCountLoading,
        visibleReports: resolvedReports,
    } = useValues(reportListLogic(resolvedProps))

    const { refresh: refreshNeedsDecision } = useActions(reportListLogic(needsDecisionProps))
    const { refresh: refreshMonitoring } = useActions(reportListLogic(monitoringProps))
    const { refresh: refreshResolved } = useActions(reportListLogic(resolvedProps))

    return {
        'needs-decision': {
            count: needsDecisionCount,
            countLoading: needsDecisionCountLoading,
            visibleReports: needsDecisionReports,
            refresh: refreshNeedsDecision,
        },
        monitoring: {
            count: monitoringCount,
            countLoading: monitoringCountLoading,
            visibleReports: monitoringReports,
            refresh: refreshMonitoring,
        },
        resolved: {
            count: resolvedCount,
            countLoading: resolvedCountLoading,
            visibleReports: resolvedReports,
            refresh: refreshResolved,
        },
    }
}

/**
 * `Inbox viewed`, fired once per Reports mount as soon as every counted section's header count has
 * settled. One event per visit, as before the sections replaced the view tabs — but the reader now
 * sees every section at once, so it carries the whole list rather than one view's slice.
 */
function useInboxViewedEvent(sections: Record<CountedSectionKey, SectionListState>): void {
    const { hasActiveFilters, sourceProductFilter, priorityFilter, scope } = useValues(inboxFiltersLogic)
    // The list stays mounted (hidden) while a report/scout detail is open, so gate the view event on
    // the list actually being the visible surface — otherwise a deep-link to a report fires a phantom
    // `Inbox viewed` and then suppresses the real one when the user navigates back to the list.
    const { selectedReportId, selectedScoutSkillName, isScratchpadOpen, isFindingsOpen, isRunsOpen, isFocusOpen } =
        useValues(inboxSceneLogic)
    const listVisible =
        !selectedReportId &&
        !selectedScoutSkillName &&
        !isScratchpadOpen &&
        !isFindingsOpen &&
        !isRunsOpen &&
        !isFocusOpen

    // A count is settled once its request is no longer in flight: loaded, refreshed, or failed
    // (count stays null). Waiting on the loading flags rather than non-null values means a scope or
    // filter refresh in progress doesn't fire the event with the previous query's counts.
    const settled = COUNTED_SECTION_KEYS.every((key) => !sections[key].countLoading)
    const firedRef = useRef(false)

    useEffect(() => {
        if (!listVisible || !settled || firedRef.current) {
            return
        }
        firedRef.current = true
        captureInboxViewed({
            // pinned: `tab` names the inbox page tab. Before the sections landed it named the report
            // view, which is no longer a surface of its own.
            tab: 'reports',
            reports: COUNTED_SECTION_KEYS.flatMap((key) => sections[key].visibleReports),
            totalCount: COUNTED_SECTION_KEYS.reduce((sum, key) => sum + (sections[key].count ?? 0), 0),
            pullsTabCount: sections.monitoring.count,
            reportsTabCount: sections['needs-decision'].count,
            hasActiveFilters,
            sourceProductFilter,
            priorityFilter,
            scope,
        })
    }, [listVisible, settled, sections, hasActiveFilters, sourceProductFilter, priorityFilter, scope])
}

/** Nothing has reached the inbox yet — the whole list is empty, not just one section. */
function ReportsEmptyState(): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)
    if (featureFlags[FEATURE_FLAGS.INBOX_SELF_DRIVING_EMPTY_STATE] === 'empty-state') {
        return <InboxWaitingForWork />
    }
    return (
        <div className="mx-auto flex max-w-md flex-col items-center gap-2 py-12 text-center">
            <div className="mb-1 flex h-12 w-12 items-center justify-center rounded-full bg-fill-primary text-secondary">
                <IconNotebook className="text-2xl" />
            </div>
            <h3 className="m-0 text-base font-semibold">Nothing in your inbox yet</h3>
            <p className="m-0 text-sm text-tertiary">
                Agents file what they find here: issues that need your judgment, pull requests to review, and the work
                already resolved.
            </p>
            <SelfDrivingInstallingHint>
                Reports will start arriving as soon as live data comes in.
            </SelfDrivingInstallingHint>
        </div>
    )
}

/**
 * The Reports tab: one filter row over a single column of collapsible sections (Needs a decision /
 * Monitoring / Resolved, plus Not actionable for staff). Each section owns its own filtered request,
 * count, and paging via the keyed `reportListLogic`, while the filter row, reviewer scope, and bulk
 * selection are shared across all of them.
 */
export function ReportsTab(): JSX.Element {
    const { isStaff } = useValues(inboxSceneLogic)
    const sections = useCountedSections()
    useInboxViewedEvent(sections)

    const visibleSections: InboxReportSectionKey[] = INBOX_REPORT_SECTION_KEYS.filter(
        (key) => isStaff || !INBOX_STAFF_ONLY_REPORT_SECTION_KEYS.includes(key)
    )
    const refreshing = COUNTED_SECTION_KEYS.some((key) => sections[key].countLoading)
    // Empty is a verdict about resolved counts: hold the sections until every count has answered, so
    // a slow first load never flashes the "nothing yet" screen at a full inbox.
    const countsSettled = COUNTED_SECTION_KEYS.every((key) => sections[key].count !== null)
    const inboxIsEmpty = countsSettled && COUNTED_SECTION_KEYS.every((key) => sections[key].count === 0)

    return (
        <div className="mx-auto flex w-full max-w-4xl flex-col gap-4 px-6 py-3">
            <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
                <div className="min-w-0 flex-1 basis-64">
                    <InboxSearchFilterBar
                        onRefresh={() => COUNTED_SECTION_KEYS.forEach((key) => sections[key].refresh())}
                        refreshing={refreshing}
                    />
                </div>
                <LemonButton
                    type="primary"
                    size="small"
                    to={urls.inboxFocus()}
                    sideIcon={<KeyboardShortcut f />}
                    tooltip="Go through the reports that need a decision one at a time"
                    className="shrink-0"
                    data-attr="inbox-focus-mode"
                >
                    Focus mode
                </LemonButton>
            </div>
            <InboxBulkSelectionBar />

            {inboxIsEmpty ? (
                <ReportsEmptyState />
            ) : (
                <div className="@container flex flex-col gap-5">
                    {visibleSections.map((sectionKey) => (
                        <InboxReportSection key={sectionKey} sectionKey={sectionKey} />
                    ))}
                </div>
            )}
        </div>
    )
}
