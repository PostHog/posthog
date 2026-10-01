import { useActions, useValues } from 'kea'

import { IconPlusSmall } from '@posthog/icons'
import {
    LemonBanner,
    LemonButton,
    LemonCard,
    LemonCollapse,
    LemonDialog,
    LemonSelect,
    LemonSkeleton,
    LemonTabs,
    Spinner,
} from '@posthog/lemon-ui'

import { pluralize } from 'lib/utils/strings'

import { ContentAutopilotDrafts } from './ContentAutopilotDrafts'
import { contentAutopilotLogic } from './contentAutopilotLogic'
import { ContentAutopilotOpportunities } from './ContentAutopilotOpportunities'
import { ContentAutopilotProposalDetail } from './ContentAutopilotProposalDetail'
import { ContentAutopilotSetup } from './ContentAutopilotSetup'

export const ContentAutopilot = (): JSX.Element => {
    const {
        profile,
        activeRun,
        siteRuns,
        reviewQueue,
        readyDraftCount,
        failedDraftCount,
        workspaceTab,
        onboardingOpen,
        siteProfiles,
        siteProfilesLoading,
        runsLoading,
        proposalsLoading,
        runMutationLoading,
        workspaceError,
        workspaceErrors,
        workspaceInitialized,
        profileDataLoaded,
        visibleOpportunities,
    } = useValues(contentAutopilotLogic)
    const { beginOnboarding, cancelRun, selectProfile, loadWorkspace, setWorkspaceTab } =
        useActions(contentAutopilotLogic)
    const loading = siteProfilesLoading || runsLoading || proposalsLoading
    const lastRun = siteRuns[0]
    const lastRunErrors = lastRun?.run_status === 'failed' ? lastRun.errors.map(({ message }) => message).join(' ') : ''
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

    if (!workspaceInitialized) {
        return <LemonSkeleton className="h-72 w-full" />
    }

    return (
        <div className="flex flex-col gap-4">
            <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                    <h1 className="m-0">Content autopilot</h1>
                    <p className="m-0 mt-1 text-muted max-w-3xl">
                        Find questions AI assistants answer without citing your site, and draft the pages that fix it.
                        Nothing is published until you download a draft and ship it yourself.
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
                    Some content autopilot data could not be loaded. {workspaceError}
                </LemonBanner>
            ) : null}

            {workspaceErrors.profiles && !profile ? (
                <LemonCard hoverEffect={false} className="p-8 text-center">
                    <h2>Sites could not be loaded</h2>
                    <p className="text-muted">Try again before adding or changing a site.</p>
                </LemonCard>
            ) : onboardingOpen || !profile ? (
                <ContentAutopilotSetup onboarding />
            ) : (
                <>
                    {!profileDataLoaded ? (
                        <LemonSkeleton className="h-72 w-full" />
                    ) : (
                        <>
                            {activeRun ? (
                                <LemonCard hoverEffect={false} className="p-4 flex items-center justify-between gap-3">
                                    <div className="flex items-center gap-3">
                                        <Spinner className="text-xl" />
                                        <div>
                                            <h3 className="m-0">Drafting pages</h3>
                                            <p className="m-0 mt-1 text-muted">
                                                PostHog is reading your pages and the pages AI assistants cite, then
                                                writing and checking each draft. This takes a few minutes per page.
                                            </p>
                                        </div>
                                    </div>
                                    <LemonButton
                                        type="secondary"
                                        status="danger"
                                        onClick={confirmCancelRun}
                                        loading={runMutationLoading}
                                    >
                                        Stop drafting
                                    </LemonButton>
                                </LemonCard>
                            ) : failedDraftCount > 0 ? (
                                <LemonBanner
                                    type="error"
                                    action={
                                        workspaceTab === 'drafts'
                                            ? undefined
                                            : { children: 'View drafts', onClick: () => setWorkspaceTab('drafts') }
                                    }
                                >
                                    {pluralize(failedDraftCount, 'draft')} from the latest run didn't pass. Open a draft
                                    to see what to fix, or regenerate it.
                                    {lastRunErrors ? ` ${lastRunErrors}` : null}
                                </LemonBanner>
                            ) : lastRun?.run_status === 'failed' ? (
                                <LemonBanner type="error">
                                    The latest run failed.{' '}
                                    {lastRunErrors || 'Select opportunities and draft them again.'}
                                </LemonBanner>
                            ) : null}

                            <LemonTabs
                                activeKey={workspaceTab}
                                onChange={setWorkspaceTab}
                                data-attr="content-autopilot-workspace-tabs"
                                tabs={[
                                    {
                                        key: 'opportunities',
                                        label: `Opportunities (${visibleOpportunities.length})`,
                                        content: <ContentAutopilotOpportunities />,
                                    },
                                    {
                                        key: 'drafts',
                                        label: readyDraftCount
                                            ? `Drafts (${readyDraftCount} ready to review)`
                                            : `Drafts (${reviewQueue.length})`,
                                        content: <ContentAutopilotDrafts />,
                                    },
                                ]}
                            />
                        </>
                    )}

                    <LemonCollapse
                        panels={[
                            {
                                key: 'settings',
                                header: `Settings for ${profile.name || profile.domain}`,
                                content: <ContentAutopilotSetup />,
                            },
                        ]}
                    />
                </>
            )}
            <ContentAutopilotProposalDetail />
        </div>
    )
}
