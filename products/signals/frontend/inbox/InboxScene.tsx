import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import React, { useEffect, useRef } from 'react'

import { IconArrowLeft } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { useResizeBreakpoints } from 'lib/hooks/useResizeObserver'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { CardSkeleton } from './components/cards/CardSkeleton'
import { ScoutDetailView } from './components/config/scouts/ScoutDetailView'
import { ScoutsRoster } from './components/config/scouts/ScoutsRoster'
import { ScoutsRosterActions } from './components/config/scouts/ScoutsRosterActions'
import { ReportDetail, ReportDetailSkeleton } from './components/detail/ReportDetail'
import { FindingsPanel } from './components/findings/FindingsPanel'
import { InboxOnboardingBanner, InboxOnboardingTakeover } from './components/onboarding/InboxOnboarding'
import { InboxWelcomeRedesign } from './components/onboarding/InboxWelcomeRedesign'
import { ScratchpadPanel } from './components/scratchpad/ScratchpadPanel'
import { AgentSetupColumn } from './components/shell/AgentSetupColumn'
import { InboxScopeSelect } from './components/shell/InboxScopeSelect'
import { InboxTabBar } from './components/shell/InboxTabBar'
import { ArchivedTab } from './components/tabs/ArchivedTab'
import { NotActionableTab } from './components/tabs/NotActionableTab'
import { PullRequestsTab } from './components/tabs/PullRequestsTab'
import { ReportsTab } from './components/tabs/ReportsTab'
import { RunsTab } from './components/tabs/RunsTab'
import { captureInboxPanelViewed } from './inboxAnalytics'
import { inboxSceneLogic } from './inboxSceneLogic'
import { inboxOnboardingLogic } from './logics/inboxOnboardingLogic'
import { scoutFleetLogic } from './logics/scoutFleetLogic'
import { INBOX_TAB_DESCRIPTION, InboxTabKey, SignalReport, SignalRun } from './types'

export const scene: SceneExport = {
    component: InboxScene,
    logic: inboxSceneLogic,
}

const LazyScoutCreateModal = React.lazy(async () => {
    const { ScoutCreateModal } = await import('./components/config/scouts/ScoutCreateModal')
    return { default: ScoutCreateModal }
})

/**
 * Hosts the `#createScout=` modal at the scene level, not in the fleet section: on wide screens
 * `/inbox/config` bounces to the setup rail, where the fleet section may never mount.
 */
function ScoutTemplateDraftModal(): JSX.Element | null {
    const { scoutTemplateDraft } = useValues(inboxSceneLogic)
    const { setScoutTemplateDraft } = useActions(inboxSceneLogic)

    if (!scoutTemplateDraft) {
        return null
    }
    return (
        <React.Suspense fallback={null}>
            <LazyScoutCreateModal
                isOpen
                initialValues={scoutTemplateDraft}
                onClose={() => setScoutTemplateDraft(null)}
                onCreated={() => {
                    // Refresh the fleet list only if it's already mounted — never mount it from here.
                    scoutFleetLogic.findMounted()?.actions.loadScoutConfigs()
                }}
            />
        </React.Suspense>
    )
}

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
}): JSX.Element {
    switch (tab) {
        case 'pulls':
            return <PullRequestsTab />
        case 'reports':
            return <ReportsTab />
        case 'not-actionable':
            return <NotActionableTab />
        case 'archived':
            return <ArchivedTab />
        case 'scouts':
            return <ScoutsRoster />
        case 'runs':
            return <RunsTab runs={signalRuns} loading={signalRunsLoading} />
        case 'config':
            return <AgentSetupColumn layout="stacked" />
    }
}

/**
 * List view: a tab bar + scope select over the active tab's body, with the agent-setup
 * widgets to the right as a rail when the scene is wide enough (≥ ~72rem). Below that width
 * the rail is dropped and the widgets live in a Configuration tab instead. Each flat report
 * tab (Pull requests / Reports / Not actionable) owns its own filtered request, count,
 * search/filter chrome, and pagination via the keyed `reportListLogic`. Runs is project-wide
 * and chrome-less.
 */
function InboxListView(): JSX.Element {
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
                        <InboxTabBar showConfigTab={!wide} onboarding={onboarding} />
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

/**
 * Detail view: replaces the list full-width. Report / PR / Not actionable render the unified
 * `ReportDetail`, which owns its own merged header (back link, title, copy link). The Runs tab no
 * longer opens an in-inbox detail — its rows link out to the standalone Tasks scene.
 */
function InboxDetailView({ report }: { report: SignalReport }): JSX.Element {
    const { activeTab } = useValues(inboxSceneLogic)
    const { reportDetailScrolled } = useActions(inboxSceneLogic)
    // Report only the first scroll per report to the logic (which fires `Inbox report scrolled` once),
    // so a fast native scroll doesn't dispatch an action on every frame.
    const scrolledReportRef = useRef<string | null>(null)

    return (
        <div
            className="flex flex-col min-h-0 flex-1 overflow-auto"
            onScroll={() => {
                if (scrolledReportRef.current !== report.id) {
                    scrolledReportRef.current = report.id
                    reportDetailScrolled()
                }
            }}
        >
            {/* Key on the report so per-report detail state (e.g. the active diff tab) resets on navigation. */}
            <ReportDetail key={report.id} report={report} tab={activeTab} />
        </div>
    )
}

/**
 * Shared chrome for the full-width scout panels (scratchpad, findings): a "Scouts" back link over the
 * panel body, rendered full-width over the list like the scout detail. Reached from their callouts.
 */
function InboxPanelView({ onBack, children }: { onBack: () => void; children: JSX.Element }): JSX.Element {
    return (
        <div className="flex flex-col min-h-0 flex-1 overflow-auto">
            <div className="px-4 pt-3">
                <LemonButton
                    type="tertiary"
                    size="small"
                    icon={<IconArrowLeft />}
                    onClick={onBack}
                    className="self-start"
                >
                    Scouts
                </LemonButton>
            </div>
            {children}
        </div>
    )
}

export function InboxScene(): JSX.Element {
    const {
        activeTab,
        selectedReportId,
        selectedReport,
        selectedReportLoading,
        selectedScoutSkillName,
        isScratchpadOpen,
        isFindingsOpen,
    } = useValues(inboxSceneLogic)
    const { setScratchpadOpen, setFindingsOpen } = useActions(inboxSceneLogic)
    const { onboardingMode, isWelcomeRedesign } = useValues(inboxOnboardingLogic)
    const { searchParams } = useValues(router)

    // Surfaces that embed inbox cards (e.g. the customer analytics feed) set a `?back=` internal path;
    // send the not-found state back there rather than the inbox, mirroring `InboxDetailFrame`.
    const rawBack = searchParams.back
    const backOverride =
        typeof rawBack === 'string' && rawBack.startsWith('/') && !rawBack.startsWith('//') ? rawBack : null

    // Detail routes (report or scout) render full-width over the list (desktop parity), but the list view
    // stays *mounted* (just hidden) rather than being unmounted. That keeps `reportListLogic` and the scroll
    // container alive, so clicking "back" lands on the same scroll position with the same loaded pages —
    // instead of remounting and resetting to the first page at the top.
    const showDetail = !!selectedReportId || !!selectedScoutSkillName || isScratchpadOpen || isFindingsOpen

    // The two scout panels replace the list without going through any tab, so they'd otherwise leave
    // no trace at all. The scout detail reports itself (it has the config to describe).
    useEffect(() => {
        if (isFindingsOpen) {
            captureInboxPanelViewed({ panel: 'findings' })
        }
    }, [isFindingsOpen])
    useEffect(() => {
        if (isScratchpadOpen) {
            captureInboxPanelViewed({ panel: 'scratchpad' })
        }
    }, [isScratchpadOpen])

    return (
        <SceneContent className="gap-y-0 border-b-0 flex-1 min-h-0">
            <div className={showDetail ? 'hidden' : 'flex flex-col gap-y-4 flex-1 min-h-0'}>
                <SceneTitleSection
                    name="Inbox"
                    // The description explains the active tab so new users can orient themselves.
                    // In the onboarding takeover the tabs are locked, so keep the overall pitch.
                    // The redesigned welcome leads with its own full-size pitch, so a description
                    // here would say the same thing twice. While the verdict is pending neither
                    // description is safe to show – either would flash and swap.
                    description={
                        onboardingMode === 'pending'
                            ? null
                            : onboardingMode === 'takeover'
                              ? isWelcomeRedesign
                                  ? null
                                  : 'Self-driving for your product. Look through code changes and reports from PostHog agents.'
                              : INBOX_TAB_DESCRIPTION[activeTab]
                    }
                    resourceType={{ type: 'inbox' }}
                    // Creating a scout is the Scouts tab's primary action, so it sits in the scene
                    // header rather than inside the roster — one predictable place, and it stays
                    // reachable when the roster is filtered down to nothing. Not while onboarding
                    // has the tab locked (or is still deciding): the roster isn't reachable then.
                    actions={
                        activeTab === 'scouts' && onboardingMode !== 'takeover' && onboardingMode !== 'pending' ? (
                            <ScoutsRosterActions />
                        ) : undefined
                    }
                />

                <div className="flex flex-col -mx-4 -mt-4 flex-1 min-h-0">
                    {/* The inbox always renders (its own list skeleton covers loading). When self-driving
                        isn't set up, the list view itself swaps in a locked "Welcome" onboarding tab; the
                        banner sits above the otherwise-normal inbox when there's already work to keep. */}
                    {onboardingMode === 'banner' && <InboxOnboardingBanner />}
                    <InboxListView />
                </div>
            </div>

            {showDetail && (
                <div className="flex flex-col -mx-4 flex-1 min-h-0">
                    {isFindingsOpen ? (
                        <InboxPanelView onBack={() => setFindingsOpen(false)}>
                            <FindingsPanel />
                        </InboxPanelView>
                    ) : isScratchpadOpen ? (
                        <InboxPanelView onBack={() => setScratchpadOpen(false)}>
                            <ScratchpadPanel />
                        </InboxPanelView>
                    ) : selectedScoutSkillName ? (
                        <ScoutDetailView skillName={selectedScoutSkillName} />
                    ) : selectedReport ? (
                        <InboxDetailView report={selectedReport} />
                    ) : selectedReportLoading ? (
                        <div className="flex flex-col min-h-0 flex-1 overflow-auto">
                            <ReportDetailSkeleton />
                        </div>
                    ) : (
                        <div className="flex flex-1 flex-col items-center justify-center gap-3 text-center">
                            <div>
                                <h3 className="m-0 text-base font-semibold">Report not found</h3>
                                <p className="m-0 mt-1 text-sm text-tertiary">
                                    This report does not exist. It may have been removed.
                                </p>
                            </div>
                            <LemonButton type="secondary" to={backOverride ?? urls.inbox(activeTab)}>
                                {backOverride ? 'Back' : 'Back to inbox'}
                            </LemonButton>
                        </div>
                    )}
                </div>
            )}

            <ScoutTemplateDraftModal />
        </SceneContent>
    )
}

export default InboxScene
