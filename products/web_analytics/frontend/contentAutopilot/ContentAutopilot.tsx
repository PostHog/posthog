import { useActions, useValues } from 'kea'

import { IconPlusSmall } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonDialog, LemonSelect, LemonSkeleton, LemonTabs } from '@posthog/lemon-ui'

import { ContentAutopilotDrafts } from './ContentAutopilotDrafts'
import { type ContentAutopilotWorkspaceTab, contentAutopilotLogic } from './contentAutopilotLogic'
import { ContentAutopilotOpportunities } from './ContentAutopilotOpportunities'
import { ContentAutopilotPromptAddModal } from './ContentAutopilotPromptAddModal'
import { ContentAutopilotPrompts } from './ContentAutopilotPrompts'
import { ContentAutopilotPromptsOverview } from './ContentAutopilotPromptsOverview'
import { ContentAutopilotProposalDetail } from './ContentAutopilotProposalDetail'
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
        workspaceInitialized,
        profileDataLoaded,
        visibleOpportunities,
    } = useValues(contentAutopilotLogic)
    const { beginOnboarding, cancelRun, selectProfile, loadWorkspace, setWorkspaceTab } =
        useActions(contentAutopilotLogic)
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

    if (!workspaceInitialized) {
        return <LemonSkeleton className="h-72 w-full" />
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

                    <LemonTabs<AiVisibilityTab>
                        activeKey={bots?.active ? 'bots' : workspaceTab}
                        onChange={selectTab}
                        data-attr="content-autopilot-workspace-tabs"
                        rightSlot={
                            activeRun ? (
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
                                key: 'prompts',
                                label: 'Prompts',
                                content: <ContentAutopilotPrompts />,
                            },
                            bots ? { key: 'bots', label: 'Bots', content: bots.content } : null,
                            {
                                key: 'opportunities',
                                label: profile ? `Opportunities (${visibleOpportunities.length})` : 'Opportunities',
                                content: (
                                    <ContentAutopilotSiteGate>
                                        <ContentAutopilotOpportunities />
                                    </ContentAutopilotSiteGate>
                                ),
                            },
                            profile
                                ? {
                                      key: 'drafts',
                                      label: readyDraftCount
                                          ? `Drafts (${readyDraftCount} ready to review)`
                                          : `Drafts (${draftRows.length})`,
                                      content: (
                                          <ContentAutopilotSiteGate>
                                              <ContentAutopilotDrafts />
                                          </ContentAutopilotSiteGate>
                                      ),
                                  }
                                : null,
                            profile
                                ? {
                                      key: 'settings',
                                      label: 'Settings',
                                      content: (
                                          <ContentAutopilotSiteGate>
                                              <ContentAutopilotSetup />
                                          </ContentAutopilotSiteGate>
                                      ),
                                  }
                                : null,
                        ]}
                    />
                </>
            )}
            <ContentAutopilotProposalDetail />
            <ContentAutopilotPromptAddModal />
        </div>
    )
}
