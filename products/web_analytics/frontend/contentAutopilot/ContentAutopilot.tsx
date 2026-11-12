import { useActions, useValues } from 'kea'

import { IconGear } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonDialog, LemonTabs } from '@posthog/lemon-ui'

import { AI_VISIBILITY_TAB_FILTERS, type AiVisibilityFilterTab } from './aiVisibilityFilters'
import { ContentAutopilotDrafts } from './ContentAutopilotDrafts'
import { ContentAutopilotFilterBar } from './ContentAutopilotFilterBar'
import { ContentAutopilotKeywords } from './ContentAutopilotKeywords'
import { type ContentAutopilotWorkspaceTab, contentAutopilotLogic } from './contentAutopilotLogic'
import { ContentAutopilotOpportunities } from './ContentAutopilotOpportunities'
import { ContentAutopilotPageHeader } from './ContentAutopilotPageHeader'
import { ContentAutopilotPromptAddModal } from './ContentAutopilotPromptAddModal'
import { ContentAutopilotPromptDetail } from './ContentAutopilotPromptDetail'
import { contentAutopilotPromptDetailLogic } from './contentAutopilotPromptDetailLogic'
import { ContentAutopilotPrompts } from './ContentAutopilotPrompts'
import { ContentAutopilotPromptsOverview } from './ContentAutopilotPromptsOverview'
import { ContentAutopilotPromptSuggestModal } from './ContentAutopilotPromptSuggestModal'
import { ContentAutopilotProposalDetail } from './ContentAutopilotProposalDetail'
import { ContentAutopilotRankings } from './ContentAutopilotRankings'
import { ContentAutopilotSetup } from './ContentAutopilotSetup'
import { ContentAutopilotSiteGate } from './ContentAutopilotSiteGate'
import { ContentAutopilotSitePicker } from './ContentAutopilotSitePicker'

const FilteredTab = ({
    tab,
    children,
}: {
    tab: Exclude<AiVisibilityFilterTab, 'prompts'>
    children: JSX.Element
}): JSX.Element => (
    <div className="flex flex-col gap-4">
        <ContentAutopilotFilterBar tab={tab} filters={AI_VISIBILITY_TAB_FILTERS[tab]} />
        {children}
    </div>
)

/** The site tabs work on one site at a time, so they carry the site picker where the other tabs carry filters. */
const SiteTab = ({ children }: { children: JSX.Element }): JSX.Element => (
    <div className="flex flex-col gap-4">
        <ContentAutopilotSitePicker />
        <ContentAutopilotSiteGate>{children}</ContentAutopilotSiteGate>
    </div>
)

export const ContentAutopilot = (): JSX.Element => {
    // Mounted here, so a prompt's own URL opens it whatever tab was last open.
    const { promptId } = useValues(contentAutopilotPromptDetailLogic)
    const {
        profile,
        activeRun,
        siteRuns,
        draftRows,
        readyDraftCount,
        latestRunErrors,
        workspaceTab,
        onboardingOpen,
        siteProfilesLoading,
        runsLoading,
        proposalsLoading,
        runMutationLoading,
        workspaceError,
        profileDataLoaded,
        visibleOpportunities,
        draftingEnabled,
    } = useValues(contentAutopilotLogic)
    const { cancelRun, loadWorkspace, setWorkspaceTab } = useActions(contentAutopilotLogic)
    // A link to a drafting tab still opens the page when drafting is off, on the overview instead.
    const visibleTab =
        !draftingEnabled && (workspaceTab === 'opportunities' || workspaceTab === 'drafts') ? 'overview' : workspaceTab
    const loading = siteProfilesLoading || runsLoading || proposalsLoading
    const lastRun = siteRuns[0]
    const confirmCancelRun = (): void => {
        if (!activeRun) {
            return
        }
        LemonDialog.open({
            title: 'Stop drafting?',
            description: 'PostHog stops after the draft it is writing now. Finished drafts stay available.',
            primaryButton: {
                children: 'Stop drafting',
                status: 'danger',
                onClick: () => cancelRun(activeRun.id),
            },
            secondaryButton: { children: 'Keep drafting' },
        })
    }

    return (
        <div className="flex flex-col gap-4">
            {workspaceError ? (
                <LemonBanner type="error" action={{ children: 'Try again', onClick: loadWorkspace, loading }}>
                    Some AI visibility data could not be loaded. {workspaceError}
                </LemonBanner>
            ) : null}

            {profile && onboardingOpen ? (
                <ContentAutopilotSetup onboarding />
            ) : (
                <>
                    {profile && profileDataLoaded && latestRunErrors.length > 0 ? (
                        <LemonBanner type={lastRun?.run_status === 'failed' ? 'error' : 'warning'}>
                            {latestRunErrors.join(' ')}
                        </LemonBanner>
                    ) : null}

                    {promptId ? (
                        <ContentAutopilotPromptDetail />
                    ) : workspaceTab === 'settings' && profile ? (
                        <div className="flex flex-col gap-4" data-attr="content-autopilot-settings-page">
                            <ContentAutopilotPageHeader
                                title="Site settings"
                                backLabel="Overview"
                                backDataAttr="content-autopilot-settings-back"
                                onBack={() => setWorkspaceTab('overview')}
                            />
                            <ContentAutopilotSitePicker />
                            <ContentAutopilotSetup />
                        </div>
                    ) : (
                        <LemonTabs<ContentAutopilotWorkspaceTab>
                            activeKey={visibleTab}
                            onChange={setWorkspaceTab}
                            data-attr="content-autopilot-workspace-tabs"
                            rightSlot={
                                <div className="flex items-center gap-2">
                                    {activeRun && draftingEnabled ? (
                                        <LemonButton
                                            type="tertiary"
                                            status="danger"
                                            size="small"
                                            onClick={confirmCancelRun}
                                            loading={runMutationLoading}
                                            data-attr="content-autopilot-stop-drafting"
                                        >
                                            Stop drafting
                                        </LemonButton>
                                    ) : null}
                                    {profile ? (
                                        <LemonButton
                                            type="secondary"
                                            size="small"
                                            icon={<IconGear />}
                                            onClick={() => setWorkspaceTab('settings')}
                                            tooltip="Site settings"
                                            aria-label="Site settings"
                                            data-attr="content-autopilot-settings"
                                        />
                                    ) : null}
                                </div>
                            }
                            tabs={[
                                {
                                    key: 'overview',
                                    label: 'Overview',
                                    content: (
                                        <FilteredTab tab="overview">
                                            <ContentAutopilotPromptsOverview />
                                        </FilteredTab>
                                    ),
                                },
                                {
                                    key: 'rankings',
                                    label: 'Rankings',
                                    content: (
                                        <FilteredTab tab="rankings">
                                            <ContentAutopilotRankings />
                                        </FilteredTab>
                                    ),
                                },
                                {
                                    key: 'prompts',
                                    label: 'Prompts',
                                    content: <ContentAutopilotPrompts />,
                                },
                                {
                                    key: 'keywords',
                                    label: 'Keywords',
                                    content: (
                                        <FilteredTab tab="keywords">
                                            <ContentAutopilotKeywords />
                                        </FilteredTab>
                                    ),
                                },
                                draftingEnabled
                                    ? {
                                          key: 'opportunities',
                                          label:
                                              profile && visibleOpportunities.length
                                                  ? `Opportunities (${visibleOpportunities.length})`
                                                  : 'Opportunities',
                                          content: (
                                              <SiteTab>
                                                  <ContentAutopilotOpportunities />
                                              </SiteTab>
                                          ),
                                      }
                                    : null,
                                profile && draftingEnabled
                                    ? {
                                          key: 'drafts',
                                          label: readyDraftCount
                                              ? `Drafts (${readyDraftCount} ready to review)`
                                              : draftRows.length
                                                ? `Drafts (${draftRows.length})`
                                                : 'Drafts',
                                          content: (
                                              <SiteTab>
                                                  <ContentAutopilotDrafts />
                                              </SiteTab>
                                          ),
                                      }
                                    : null,
                            ]}
                        />
                    )}
                </>
            )}
            <ContentAutopilotProposalDetail />
            <ContentAutopilotPromptAddModal />
            <ContentAutopilotPromptSuggestModal />
        </div>
    )
}
