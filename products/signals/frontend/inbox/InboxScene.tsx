import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import React, { useEffect, useRef } from 'react'

import { IconArrowLeft } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { useKeyboardHotkeys } from 'lib/hooks/useKeyboardHotkeys'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { CardSkeleton } from './components/cards/CardSkeleton'
import { ScoutDetailView } from './components/config/scouts/ScoutDetailView'
import { ScoutsRoster } from './components/config/scouts/ScoutsRoster'
import { ScoutsRosterActions } from './components/config/scouts/ScoutsRosterActions'
import { ReportDetail, ReportDetailSkeleton } from './components/detail/ReportDetail'
import { ReportDetailLegacy, ReportDetailSkeletonLegacy } from './components/detail/ReportDetailLegacy'
import { FindingsPanel } from './components/findings/FindingsPanel'
import { InboxOnboardingBanner, InboxOnboardingTakeover } from './components/onboarding/InboxOnboarding'
import { InboxWelcomeRedesign } from './components/onboarding/InboxWelcomeRedesign'
import { ScratchpadPanel } from './components/scratchpad/ScratchpadPanel'
import { InboxListViewLegacy } from './components/shell/InboxListViewLegacy'
import { InboxTabBar } from './components/shell/InboxTabBar'
import { ReportsTab } from './components/tabs/ReportsTab'
import { RunsTab } from './components/tabs/RunsTab'
import { SettingsTab } from './components/tabs/SettingsTab'
import { InboxTriageView } from './components/triage/InboxTriageView'
import { captureInboxPanelViewed } from './inboxAnalytics'
import { inboxSceneLogic } from './inboxSceneLogic'
import { inboxOnboardingLogic } from './logics/inboxOnboardingLogic'
import { scoutFleetLogic } from './logics/scoutFleetLogic'
import { INBOX_LEGACY_TAB_DESCRIPTION, INBOX_TAB_DESCRIPTION, InboxTabKey, SignalReport } from './types'

export const scene: SceneExport = {
    component: InboxScene,
    logic: inboxSceneLogic,
}

const LazyScoutCreateModal = React.lazy(async () => {
    const { ScoutCreateModal } = await import('./components/config/scouts/ScoutCreateModal')
    return { default: ScoutCreateModal }
})

/** Hosts the `#createScout=` modal at the scene level, so it opens from any tab, not just the roster. */
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

function ActiveTabBody({ tab }: { tab: InboxTabKey }): JSX.Element | null {
    switch (tab) {
        case 'reports':
            return <ReportsTab />
        case 'scouts':
            return <ScoutsRoster />
        case 'settings':
            return <SettingsTab />
        // Legacy tab segments are redirected before they can become active under the redesign.
        default:
            return null
    }
}

/**
 * List view: the page tab bar (Reports / Scouts / Settings) over the active tab's body. The Reports
 * tab owns its filters and keyed report lists; Scouts is the roster in the same column;
 * Settings is every agent-setup control on one page.
 */
function InboxListView(): JSX.Element {
    const { activeTab } = useValues(inboxSceneLogic)
    const { onboardingMode, isWelcomeRedesign } = useValues(inboxOnboardingLogic)
    // Self-driving isn't set up and the inbox is empty: the inbox becomes a single locked "Welcome"
    // tab (the other tabs are visible but disabled) whose body is the onboarding card, so the
    // onboarding is the whole story – just run the one command.
    const onboarding = onboardingMode === 'takeover'
    // The takeover verdict is still settling: commit to neither UI. Rendering the tab bar here is
    // what caused the normal inbox to flash in and get replaced by the welcome page.
    const pending = onboardingMode === 'pending'

    // Settings renders no report list, so `Inbox viewed` never fires for it. Same once-per-visit
    // guard as the report list. The panel name predates the tab's rename (see `InboxPanelName`).
    const panelViewFiredRef = useRef<InboxTabKey | null>(null)
    useEffect(() => {
        if (activeTab !== 'settings' || onboarding || pending) {
            panelViewFiredRef.current = null
            return
        }
        if (panelViewFiredRef.current === activeTab) {
            return
        }
        panelViewFiredRef.current = activeTab
        captureInboxPanelViewed({ panel: 'config' })
    }, [activeTab, onboarding, pending])

    return (
        <div className="flex flex-col min-h-0 flex-1 min-w-0">
            {/* pl-5 (20px) aligns the first tab label with the SceneTitleSection description above. */}
            {/* The redesigned welcome (experiment test arm) is a full-pane page with no tab
                row at all; control keeps the locked "Welcome" tab over the disabled real tabs. */}
            {!isWelcomeRedesign && !pending && (
                <div className="border-b border-primary pl-5 pr-6 shrink-0">
                    <InboxTabBar onboarding={onboarding} />
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
                    <ActiveTabBody tab={activeTab} />
                )}
            </div>
        </div>
    )
}

/**
 * Detail view: replaces the list full-width. Renders the unified `ReportDetail`, which owns its own
 * header (back link, actions) and the evidence-first two-column layout.
 */
function InboxDetailView({ report }: { report: SignalReport }): JSX.Element {
    const { activeTab, isRedesign } = useValues(inboxSceneLogic)
    const { reportDetailScrolled } = useActions(inboxSceneLogic)
    // Report only the first scroll per report to the logic (which fires `Inbox report scrolled` once),
    // so a fast native scroll doesn't dispatch an action on every frame.
    const scrolledReportRef = useRef<string | null>(null)

    return (
        <div
            className={
                isRedesign
                    ? '-mt-2 flex flex-col min-h-0 flex-1 overflow-auto'
                    : 'flex flex-col min-h-0 flex-1 overflow-auto'
            }
            onScroll={() => {
                if (scrolledReportRef.current !== report.id) {
                    scrolledReportRef.current = report.id
                    reportDetailScrolled()
                }
            }}
        >
            {/* Key on the report so per-report detail state (e.g. the active diff tab) resets on navigation. */}
            {isRedesign ? (
                <ReportDetail key={report.id} report={report} />
            ) : (
                <ReportDetailLegacy key={report.id} report={report} tab={activeTab} />
            )}
        </div>
    )
}

/**
 * Shared chrome for the full-width scout panels (scratchpad, findings, runs): a "Scouts" back link
 * over the panel body, rendered full-width over the list like the scout detail.
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

/** The runs panel body, with its own once-per-open view event since it renders no report list. */
function InboxRunsPanel(): JSX.Element {
    const { signalRuns, signalRunsLoading } = useValues(inboxSceneLogic)
    // Hold until the load settles so the count is real.
    const panelViewFiredRef = useRef(false)
    useEffect(() => {
        if (signalRunsLoading || panelViewFiredRef.current) {
            return
        }
        panelViewFiredRef.current = true
        captureInboxPanelViewed({ panel: 'runs', itemCount: signalRuns.length })
    }, [signalRunsLoading, signalRuns.length])

    return <RunsTab runs={signalRuns} loading={signalRunsLoading} />
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
        isRunsOpen,
        isTriageOpen,
        isRedesign,
    } = useValues(inboxSceneLogic)
    const { setScratchpadOpen, setFindingsOpen, setRunsOpen } = useActions(inboxSceneLogic)
    const { onboardingMode, isWelcomeRedesign } = useValues(inboxOnboardingLogic)
    const { searchParams } = useValues(router)

    // Surfaces that embed inbox cards (e.g. the customer analytics feed) set a `?back=` internal path;
    // send the not-found state back there rather than the inbox, mirroring `InboxDetailFrame`.
    const rawBack = searchParams.back
    const backOverride =
        typeof rawBack === 'string' && rawBack.startsWith('/') && !rawBack.startsWith('//') ? rawBack : null

    // Full-width surfaces (report, scout, the scout panels, runs, triage mode) render over the list,
    // but the list view stays *mounted* (just hidden) rather than being unmounted. That keeps
    // `reportListLogic` and the scroll container alive, so clicking "back" lands on the same scroll
    // position with the same loaded pages — instead of remounting and resetting to the first page.
    const showDetail =
        !!selectedReportId ||
        !!selectedScoutSkillName ||
        isScratchpadOpen ||
        isFindingsOpen ||
        isRunsOpen ||
        isTriageOpen

    // `t` opens triage mode from the report list. Not while a surface covers the list, not while
    // the inbox is locked behind onboarding, and not with the flag off (there is no triage mode).
    const listInteractive = isRedesign && !showDetail && activeTab === 'reports' && onboardingMode === 'none'
    useKeyboardHotkeys(
        {
            t: { action: () => router.actions.push(urls.inboxTriage()), disabled: !listInteractive },
        },
        [listInteractive]
    )

    // The scout panels replace the list without going through any tab, so they'd otherwise leave
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
                              : (isRedesign ? INBOX_TAB_DESCRIPTION : INBOX_LEGACY_TAB_DESCRIPTION)[activeTab]
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
                    {isRedesign ? <InboxListView /> : <InboxListViewLegacy />}
                </div>
            </div>

            {showDetail && (
                <div className="flex flex-col -mx-4 flex-1 min-h-0">
                    {isTriageOpen ? (
                        <InboxTriageView />
                    ) : isFindingsOpen ? (
                        <InboxPanelView onBack={() => setFindingsOpen(false)}>
                            <FindingsPanel />
                        </InboxPanelView>
                    ) : isScratchpadOpen ? (
                        <InboxPanelView onBack={() => setScratchpadOpen(false)}>
                            <ScratchpadPanel />
                        </InboxPanelView>
                    ) : isRunsOpen ? (
                        <InboxPanelView onBack={() => setRunsOpen(false)}>
                            <InboxRunsPanel />
                        </InboxPanelView>
                    ) : selectedScoutSkillName ? (
                        <ScoutDetailView skillName={selectedScoutSkillName} />
                    ) : selectedReport ? (
                        <InboxDetailView report={selectedReport} />
                    ) : selectedReportLoading ? (
                        isRedesign ? (
                            <div className="-mt-2 flex flex-col min-h-0 flex-1 overflow-auto">
                                <ReportDetailSkeleton />
                            </div>
                        ) : (
                            <div className="flex flex-col min-h-0 flex-1 overflow-auto">
                                <ReportDetailSkeletonLegacy />
                            </div>
                        )
                    ) : (
                        <div className="flex flex-1 flex-col items-center justify-center gap-3 text-center">
                            <div>
                                <h3 className="m-0 text-base font-semibold">Report not found</h3>
                                <p className="m-0 mt-1 text-sm text-tertiary">
                                    This report does not exist. It may have been removed.
                                </p>
                            </div>
                            <LemonButton
                                type="secondary"
                                to={backOverride ?? urls.inbox(isRedesign ? 'reports' : activeTab)}
                            >
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
