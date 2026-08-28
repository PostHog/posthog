import { useValues } from 'kea'
import { useEffect, useRef } from 'react'

import { useResizeBreakpoints } from 'lib/hooks/useResizeObserver'

import { captureInboxPanelViewed } from '../../inboxAnalytics'
import { inboxSceneLogic } from '../../inboxSceneLogic'
import { inboxOnboardingLogic } from '../../logics/inboxOnboardingLogic'
import { InboxTabKey, SignalRun } from '../../types'
import { CardSkeleton } from '../cards/CardSkeleton'
import { ScoutsRosterLegacy } from '../config/scouts/ScoutsRosterLegacy'
import { InboxOnboardingTakeover } from '../onboarding/InboxOnboarding'
import { InboxWelcomeRedesign } from '../onboarding/InboxWelcomeRedesign'
import { ArchivedTab } from '../tabs/ArchivedTab'
import { NotActionableTab } from '../tabs/NotActionableTab'
import { PullRequestsTab } from '../tabs/PullRequestsTab'
import { ReportsTabLegacy } from '../tabs/ReportsTabLegacy'
import { RunsTab } from '../tabs/RunsTab'
import { AgentSetupColumn } from './AgentSetupColumn'
import { InboxScopeSelect } from './InboxScopeSelect'
import { InboxTabBarLegacy } from './InboxTabBarLegacy'

/** Min scene-container width at which the setup rail fits beside the list. */
const SETUP_RAIL_MIN_PX = 1024

/** Tabs that show the centered report list (scope chrome in the header). Runs/Configuration are special. */
function isReportListTab(tab: InboxTabKey): boolean {
    return tab === 'pulls' || tab === 'reports' || tab === 'not-actionable' || tab === 'archived'
}

function ActiveTabBody({
    tab,
    signalRuns,
    signalRunsLoading,
}: {
    tab: InboxTabKey
    signalRuns: SignalRun[]
    signalRunsLoading: boolean
}): JSX.Element | null {
    switch (tab) {
        case 'pulls':
            return <PullRequestsTab />
        case 'reports':
            return <ReportsTabLegacy />
        case 'not-actionable':
            return <NotActionableTab />
        case 'archived':
            return <ArchivedTab />
        case 'scouts':
            return <ScoutsRosterLegacy />
        case 'runs':
            return <RunsTab runs={signalRuns} loading={signalRunsLoading} />
        case 'config':
            return <AgentSetupColumn layout="stacked" />
        // The redesign's Settings tab is redirected to Configuration before it can become active.
        case 'settings':
            return null
    }
}

/**
 * The inbox list view with the redesign flag off: a tab bar + scope select over the active tab's
 * body, with the agent-setup widgets to the right as a rail when the scene is wide enough
 * (≥ ~72rem). Below that width the rail is dropped and the widgets live in a Configuration tab
 * instead. Each flat report tab (Pull requests / Reports / Not actionable) owns its own filtered
 * request, count, search/filter chrome, and pagination via the keyed `reportListLogic`. Runs is
 * project-wide and chrome-less.
 */
export function InboxListViewLegacy(): JSX.Element {
    const { activeTab, signalRuns, signalRunsLoading } = useValues(inboxSceneLogic)
    const { onboardingMode, isWelcomeRedesign } = useValues(inboxOnboardingLogic)
    const { ref: widthRef, size } = useResizeBreakpoints(
        { 0: 'narrow', [SETUP_RAIL_MIN_PX]: 'wide' },
        { initialSize: 'wide' }
    )
    const wide = size === 'wide'
    // Self-driving isn't set up and the inbox is empty: the inbox becomes a single locked "Welcome"
    // tab (the other tabs are visible but disabled) whose body is the onboarding card. The setup rail
    // is dropped too, so the onboarding is the whole story – just run the one command.
    const onboarding = onboardingMode === 'takeover'
    // The takeover verdict is still settling: commit to neither UI. Rendering the tab bar or the
    // rail here is what caused the normal inbox to flash in and get replaced by the welcome page.
    const pending = onboardingMode === 'pending'
    // The Scouts tab is a full-width table, and the rail's own scout widget just links here — so
    // the rail would be both redundant and the reason the table has nowhere to breathe.
    const showRail = wide && !onboarding && !pending && activeTab !== 'scouts'
    // The rail and the Configuration tab are mutually exclusive – never leave 'config' active
    // (e.g. via a deep link) while the rail shows, or the rail and a config body would both appear.
    const effectiveTab = showRail && activeTab === 'config' ? 'pulls' : activeTab

    // Runs and Configuration don't render `InboxReportList`, so `Inbox viewed` never fires for them.
    // Same once-per-visit guard as the report list: hold Runs until its load settles so the count is real.
    const panelViewFiredRef = useRef<string | null>(null)
    useEffect(() => {
        if (effectiveTab !== 'runs' && effectiveTab !== 'config') {
            panelViewFiredRef.current = null
            return
        }
        if (effectiveTab === 'runs' && signalRunsLoading) {
            return
        }
        if (panelViewFiredRef.current === effectiveTab) {
            return
        }
        panelViewFiredRef.current = effectiveTab
        captureInboxPanelViewed({
            panel: effectiveTab,
            itemCount: effectiveTab === 'runs' ? signalRuns.length : null,
        })
    }, [effectiveTab, signalRunsLoading, signalRuns.length])

    return (
        <div ref={widthRef} className="flex min-h-0 flex-1">
            <div className="flex flex-col min-h-0 flex-1 min-w-0">
                {/* pl-5 (20px) aligns the first tab label with the SceneTitleSection description above;
                    pr-6 matches the report list's px-6 so the scope select shares the list's right edge. */}
                {/* The redesigned welcome (experiment test arm) is a full-pane page with no tab
                    row at all; control keeps the locked "Welcome" tab over the disabled real tabs. */}
                {!isWelcomeRedesign && !pending && (
                    <div className="flex items-end justify-between gap-2 border-b border-primary pl-5 pr-6 shrink-0">
                        <InboxTabBarLegacy showConfigTab={!wide} onboarding={onboarding} />
                        {!onboarding && isReportListTab(effectiveTab) && (
                            <div className="pb-1.5">
                                <InboxScopeSelect />
                            </div>
                        )}
                    </div>
                )}
                <div className="flex-1 overflow-auto min-h-0">
                    {pending ? (
                        <div className="mx-auto max-w-4xl px-6 py-4">
                            <CardSkeleton count={4} variant="cards" />
                        </div>
                    ) : onboarding ? (
                        isWelcomeRedesign ? (
                            <InboxWelcomeRedesign />
                        ) : (
                            <InboxOnboardingTakeover />
                        )
                    ) : (
                        <ActiveTabBody
                            tab={effectiveTab}
                            signalRuns={signalRuns}
                            signalRunsLoading={signalRunsLoading}
                        />
                    )}
                </div>
            </div>
            {showRail && (
                <aside className="shrink-0 w-80 overflow-auto min-h-0 border-l border-primary">
                    <AgentSetupColumn layout="rail" />
                </aside>
            )}
        </div>
    )
}
