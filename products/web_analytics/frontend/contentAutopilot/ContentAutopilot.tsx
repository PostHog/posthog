import { useActions, useValues } from 'kea'

import { IconGear, IconPlusSmall } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonDialog, LemonSelect, LemonTabs } from '@posthog/lemon-ui'

import { ContentAutopilotDrafts } from './ContentAutopilotDrafts'
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

export interface ContentAutopilotBotsTab {
    active: boolean
    open: () => void
    close: () => void
    content: JSX.Element
}

type AiVisibilityTab = ContentAutopilotWorkspaceTab | 'bots'

export const ContentAutopilot = ({ bots }: { bots?: ContentAutopilotBotsTab }): JSX.Element => {
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
        siteProfiles,
        siteProfilesLoading,
        runsLoading,
        proposalsLoading,
        runMutationLoading,
        workspaceError,
        profileDataLoaded,
        visibleOpportunities,
        draftingEnabled,
    } = useValues(contentAutopilotLogic)
    const { beginOnboarding, cancelRun, selectProfile, loadWorkspace, setWorkspaceTab } =
        useActions(contentAutopilotLogic)
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
    const selectTab = (tab: AiVisibilityTab): void => {
        if (tab === 'bots') {
            bots?.open()
            return
        }
        if (bots?.active) {
            bots.close()
        }
        setWorkspaceTab(tab)
    }

    return (
        <div className="flex flex-col gap-4">
            <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                    <h1 className="m-0">AI visibility</h1>
                    <p className="m-0 mt-1 text-muted max-w-3xl">
                        Track whether AI assistants mention and cite your site when they answer the prompts you care
                        about.
                    </p>
                </div>
                {profile && !onboardingOpen ? (
                    <div className="flex flex-wrap items-center gap-2">
                        <LemonSelect
                            aria-label="Site"
                            value={profile.id}
                            onChange={selectProfile}
                            options={siteProfiles.map((siteProfile) => ({
                                value: siteProfile.id,
                                label: siteProfile.name || siteProfile.domain,
                            }))}
                        />
                        <LemonButton type="secondary" icon={<IconPlusSmall />} onClick={beginOnboarding}>
                            Add site
                        </LemonButton>
                        <LemonButton
                            type="secondary"
                            icon={<IconGear />}
                            active={workspaceTab === 'settings'}
                            onClick={() => selectTab('settings')}
                            tooltip="Site settings"
                            aria-label="Site settings"
                            data-attr="content-autopilot-settings"
                        />
                    </div>
                ) : null}
            </div>

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
                            <ContentAutopilotSetup />
                        </div>
                    ) : (
                        <LemonTabs<AiVisibilityTab>
                            activeKey={bots?.active ? 'bots' : visibleTab}
                            onChange={selectTab}
                            data-attr="content-autopilot-workspace-tabs"
                            rightSlot={
                                activeRun && draftingEnabled ? (
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
                                ) : null
                            }
                            tabs={[
                                {
                                    key: 'overview',
                                    label: 'Overview',
                                    content: <ContentAutopilotPromptsOverview />,
                                },
                                {
                                    key: 'rankings',
                                    label: 'Rankings',
                                    content: <ContentAutopilotRankings />,
                                },
                                {
                                    key: 'prompts',
                                    label: 'Prompts',
                                    content: <ContentAutopilotPrompts />,
                                },
                                {
                                    key: 'keywords',
                                    label: 'Keywords',
                                    content: <ContentAutopilotKeywords />,
                                },
                                bots ? { key: 'bots', label: 'Bots', content: bots.content } : null,
                                draftingEnabled
                                    ? {
                                          key: 'opportunities',
                                          label:
                                              profile && visibleOpportunities.length
                                                  ? `Opportunities (${visibleOpportunities.length})`
                                                  : 'Opportunities',
                                          content: (
                                              <ContentAutopilotSiteGate>
                                                  <ContentAutopilotOpportunities />
                                              </ContentAutopilotSiteGate>
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
                                              <ContentAutopilotSiteGate>
                                                  <ContentAutopilotDrafts />
                                              </ContentAutopilotSiteGate>
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
