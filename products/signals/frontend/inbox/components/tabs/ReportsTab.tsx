import { useValues } from 'kea'
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
    INBOX_SCOPE_ENTIRE_PROJECT,
    INBOX_STAFF_ONLY_REPORT_SECTION_KEYS,
    InboxReportSectionKey,
    SignalReport,
} from '../../types'
import { InboxWaitingForWork } from '../emptyState/InboxWaitingForWork'
import { InboxReportSection } from '../InboxReportSection'
import { SelfDrivingInstallingHint } from '../SelfDrivingInstallingHint'
import { InboxBulkSelectionBar } from '../shell/InboxBulkSelectionBar'
import { InboxReportFilters } from '../shell/InboxReportFilters'
import { InboxScopeSelect } from '../shell/InboxScopeSelect'

/**
 * The sections that make up "the inbox" for the `Inbox viewed` event. Not actionable is left out: it
 * is a staff triage surface, and counting it would report a non-empty inbox on a project that has
 * surfaced nothing worth acting on. The empty-state verdict is a separate question, answered over
 * the sections the current user can actually see.
 */
const COUNTED_SECTION_KEYS = ['needs-decision', 'monitoring', 'resolved'] as const

type CountedSectionKey = (typeof COUNTED_SECTION_KEYS)[number]

interface SectionListState {
    count: number | null
    countLoading: boolean
    visibleReports: SignalReport[]
}

/**
 * Every section's header count and rendered rows, keyed by section. All four logics are mounted
 * regardless of who is looking, so the hooks never change shape when the staff flag resolves;
 * callers decide which sections matter to them.
 *
 * Read one value at a time rather than spreading what `useValues` returns: it hands back a proxy
 * whose properties are subscribing getters, and spreading it yields an empty object — silently, and
 * with a type that still claims every value is there.
 */
function useSectionStates(): Record<InboxReportSectionKey, SectionListState> {
    const needsDecisionProps = {
        sectionKey: 'needs-decision' as const,
        listParams: INBOX_REPORT_SECTION_LIST_PARAMS['needs-decision'],
    }
    const monitoringProps = {
        sectionKey: 'monitoring' as const,
        listParams: INBOX_REPORT_SECTION_LIST_PARAMS.monitoring,
    }
    const resolvedProps = { sectionKey: 'resolved' as const, listParams: INBOX_REPORT_SECTION_LIST_PARAMS.resolved }
    const notActionableProps = {
        sectionKey: 'not-actionable' as const,
        listParams: INBOX_REPORT_SECTION_LIST_PARAMS['not-actionable'],
    }

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
    const {
        count: notActionableCount,
        countLoading: notActionableCountLoading,
        visibleReports: notActionableReports,
    } = useValues(reportListLogic(notActionableProps))

    return {
        'needs-decision': {
            count: needsDecisionCount,
            countLoading: needsDecisionCountLoading,
            visibleReports: needsDecisionReports,
        },
        monitoring: {
            count: monitoringCount,
            countLoading: monitoringCountLoading,
            visibleReports: monitoringReports,
        },
        resolved: {
            count: resolvedCount,
            countLoading: resolvedCountLoading,
            visibleReports: resolvedReports,
        },
        'not-actionable': {
            count: notActionableCount,
            countLoading: notActionableCountLoading,
            visibleReports: notActionableReports,
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
    const { selectedReportId, selectedScoutSkillName, isScratchpadOpen, isFindingsOpen, isRunsOpen, isTriageOpen } =
        useValues(inboxSceneLogic)
    const listVisible =
        !selectedReportId &&
        !selectedScoutSkillName &&
        !isScratchpadOpen &&
        !isFindingsOpen &&
        !isRunsOpen &&
        !isTriageOpen

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
                Agents file what they find here: reports waiting on a pull request, pull requests for you to review, and
                the work already resolved.
            </p>
            <SelfDrivingInstallingHint>
                Reports will start arriving as soon as live data comes in.
            </SelfDrivingInstallingHint>
        </div>
    )
}

/**
 * The Reports tab: one toolbar over a single column of collapsible sections (Needs a PR / Review and
 * merge / Resolved, plus Not actionable for staff). Each section owns its own filtered request,
 * count, and paging via the keyed `reportListLogic`, while the toolbar, reviewer scope, and bulk
 * selection are shared across all of them.
 */
export function ReportsTab(): JSX.Element {
    const { isStaff } = useValues(inboxSceneLogic)
    const { hasActiveFilters, scope } = useValues(inboxFiltersLogic)
    const sections = useSectionStates()
    useInboxViewedEvent(sections)

    const visibleSections: InboxReportSectionKey[] = INBOX_REPORT_SECTION_KEYS.filter(
        (key) => isStaff || !INBOX_STAFF_ONLY_REPORT_SECTION_KEYS.includes(key)
    )
    // "Nothing yet" is a claim about the whole project, so it only holds with no filters and the
    // project-wide scope; a narrowed view that matches nothing shows the sections with their own
    // per-section copy instead. The verdict is over the sections this user can see, so staff still
    // reach Not actionable when it is the only section with reports. Hold the sections until every
    // count has answered, so a slow first load never flashes the "nothing yet" screen at a full inbox.
    const unfilteredView = !hasActiveFilters && scope === INBOX_SCOPE_ENTIRE_PROJECT
    const countsSettled = visibleSections.every((key) => sections[key].count !== null)
    const inboxIsEmpty = unfilteredView && countsSettled && visibleSections.every((key) => sections[key].count === 0)

    return (
        <div className="mx-auto flex w-full max-w-4xl flex-col gap-4 px-6 py-3">
            <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
                <InboxReportFilters />
                <div className="ml-auto flex shrink-0 items-center gap-2">
                    <LemonButton
                        type="primary"
                        size="small"
                        to={urls.inboxTriage()}
                        sideIcon={<KeyboardShortcut t />}
                        tooltip="Go through the reports that need a pull request one at a time"
                        data-attr="inbox-triage-mode"
                    >
                        Triage mode
                    </LemonButton>
                    <InboxScopeSelect />
                </div>
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
