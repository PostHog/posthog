import { useActions, useValues } from 'kea'

import { IconGear } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonDialog, LemonTabs } from '@posthog/lemon-ui'

import { AI_VISIBILITY_TAB_FILTERS, type AiVisibilityFilterTab } from './aiVisibilityFilters'
import { ContentAutopilotCitationsModal } from './ContentAutopilotCitationsModal'
import { ContentAutopilotFilterBar } from './ContentAutopilotFilterBar'
import { ContentAutopilotKeywords } from './ContentAutopilotKeywords'
import { type ContentAutopilotWorkspaceTab, contentAutopilotLogic } from './contentAutopilotLogic'
import { ContentAutopilotPageHeader } from './ContentAutopilotPageHeader'
import { ContentAutopilotPromptAddModal } from './ContentAutopilotPromptAddModal'
import { ContentAutopilotPromptDetail } from './ContentAutopilotPromptDetail'
import { contentAutopilotPromptDetailLogic } from './contentAutopilotPromptDetailLogic'
import { ContentAutopilotPrompts } from './ContentAutopilotPrompts'
import { ContentAutopilotPromptsOverview } from './ContentAutopilotPromptsOverview'
import { ContentAutopilotPromptSuggestModal } from './ContentAutopilotPromptSuggestModal'
import { ContentAutopilotProposalDetail } from './ContentAutopilotProposalDetail'
import { ContentAutopilotRankings } from './ContentAutopilotRankings'
import { ContentAutopilotSettings } from './ContentAutopilotSettings'
import { ContentAutopilotSetup } from './ContentAutopilotSetup'
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

export const ContentAutopilot = (): JSX.Element => {
    // Mounted here, so a prompt's own URL opens it whatever tab was last open.
    const { promptId } = useValues(contentAutopilotPromptDetailLogic)
    const {
        profile,
        activeRun,
        siteRuns,
        latestRunErrors,
        workspaceTab,
        onboardingOpen,
        siteProfilesLoading,
        runsLoading,
        proposalsLoading,
        runMutationLoading,
        workspaceError,
        profileDataLoaded,
        draftingEnabled,
    } = useValues(contentAutopilotLogic)
    const { cancelRun, loadWorkspace, setWorkspaceTab } = useActions(contentAutopilotLogic)
    // The drafting tabs are gone, so an old link to one opens the overview.
    const visibleTab = workspaceTab === 'opportunities' || workspaceTab === 'drafts' ? 'overview' : workspaceTab
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
                                title="Settings"
                                backLabel="Overview"
                                backDataAttr="content-autopilot-settings-back"
                                onBack={() => setWorkspaceTab('overview')}
                            />
                            <ContentAutopilotSitePicker />
                            <ContentAutopilotSettings />
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
                                            tooltip="Settings"
                                            aria-label="Settings"
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
                            ]}
                        />
                    )}
                </>
            )}
            <ContentAutopilotProposalDetail />
            <ContentAutopilotPromptAddModal />
            <ContentAutopilotPromptSuggestModal />
            <ContentAutopilotCitationsModal />
        </div>
    )
}
