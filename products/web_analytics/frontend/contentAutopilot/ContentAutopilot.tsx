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
    LemonTag,
} from '@posthog/lemon-ui'

import { contentAutopilotLogic } from './contentAutopilotLogic'
import { ContentAutopilotProposalDetail } from './ContentAutopilotProposalDetail'
import { ContentAutopilotProposalSection } from './ContentAutopilotProposalSection'
import { ContentAutopilotSetup } from './ContentAutopilotSetup'

export const ContentAutopilot = (): JSX.Element => {
    const {
        profile,
        activeRun,
        siteRuns,
        newContentProposals,
        pageImprovementProposals,
        onboardingOpen,
        siteProfiles,
        siteProfilesLoading,
        runsLoading,
        proposalsLoading,
        runMutationLoading,
        workspaceError,
        workspaceErrors,
        workspaceInitialized,
    } = useValues(contentAutopilotLogic)
    const { beginOnboarding, startRun, cancelRun, selectProfile, selectProposal, loadWorkspace } =
        useActions(contentAutopilotLogic)
    const loading = siteProfilesLoading || runsLoading || proposalsLoading
    const lastRun = siteRuns[0]
    const runDisabledReason = activeRun ? 'A content run is already in progress for this site' : undefined
    const confirmCancelRun = (): void => {
        if (!activeRun) {
            return
        }
        LemonDialog.open({
            title: 'Cancel this content run?',
            description: 'PostHog will stop processing this run. Completed proposals will remain available.',
            primaryButton: {
                children: 'Cancel run',
                status: 'danger',
                onClick: () => cancelRun(activeRun.id),
            },
            secondaryButton: { children: 'Keep running' },
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
                        Turn site, search, referral, and crawler signals into reviewable content. PostHog never
                        publishes or merges automatically.
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
                            type="primary"
                            icon={<IconPlusSmall />}
                            onClick={startRun}
                            loading={runMutationLoading}
                            disabledReason={runDisabledReason}
                        >
                            Create content
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
                    {!profile.search_console_enabled ? (
                        <LemonBanner type="warning">
                            Google Search Console is not enabled. Recommendations use available Web analytics data and
                            are labeled as lower confidence.
                        </LemonBanner>
                    ) : null}

                    {activeRun ? (
                        <LemonCard hoverEffect={false} className="p-4 flex items-center justify-between gap-3">
                            <div>
                                <div className="flex items-center gap-2">
                                    <h3 className="m-0">Researching content opportunities</h3>
                                    <LemonTag type="completion">{activeRun.run_status}</LemonTag>
                                </div>
                                <p className="m-0 mt-1 text-muted">
                                    PostHog is analyzing current data, ranking opportunities, and validating drafts.
                                </p>
                            </div>
                            <LemonButton
                                type="secondary"
                                status="danger"
                                onClick={confirmCancelRun}
                                loading={runMutationLoading}
                            >
                                Cancel run
                            </LemonButton>
                        </LemonCard>
                    ) : lastRun?.run_status === 'failed' ? (
                        <LemonBanner type="error">
                            The latest run failed.{' '}
                            {lastRun.errors.map(({ message }) => message).join(' ') || 'Start another run to retry.'}
                        </LemonBanner>
                    ) : null}

                    {newContentProposals.length === 0 && pageImprovementProposals.length === 0 ? (
                        <LemonCard hoverEffect={false} className="p-8 text-center">
                            <h2>No proposals yet</h2>
                            <p className="text-muted max-w-xl mx-auto">
                                Start a run to research one new article and up to five focused page improvements.
                            </p>
                            <LemonButton
                                type="primary"
                                onClick={startRun}
                                loading={runMutationLoading}
                                disabledReason={runDisabledReason}
                            >
                                Create content
                            </LemonButton>
                        </LemonCard>
                    ) : (
                        <>
                            <ContentAutopilotProposalSection
                                title="New content"
                                description="Original articles for topics people search for that do not have a dedicated page."
                                proposals={newContentProposals}
                                onReview={selectProposal}
                            />
                            <ContentAutopilotProposalSection
                                title="Page improvements"
                                description="Focused metadata, linking, and content changes."
                                proposals={pageImprovementProposals}
                                onReview={selectProposal}
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
