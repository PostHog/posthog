import { useActions, useValues } from 'kea'

import { IconArrowLeft, IconArrowRight } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonCard } from '@posthog/lemon-ui'

import { ContentAutopilotDeliveryFields } from './ContentAutopilotDeliveryFields'
import { contentAutopilotLogic } from './contentAutopilotLogic'
import { ContentAutopilotSetupStepIndicator } from './ContentAutopilotSetupStepIndicator'
import { ContentAutopilotSiteFields } from './ContentAutopilotSiteFields'
import { ContentAutopilotSourceFields } from './ContentAutopilotSourceFields'

export const ContentAutopilotSetup = ({ onboarding = false }: { onboarding?: boolean }): JSX.Element => {
    const { siteProfiles, profileDraft, onboardingStep, discoveredSite, discoveredSiteLoading, savedProfileLoading } =
        useValues(contentAutopilotLogic)
    const { cancelOnboarding, discoverSite, saveProfile, setOnboardingStep } = useActions(contentAutopilotLogic)
    const isGitHub = profileDraft.deliveryMode === 'github'
    const saveDisabledReason = !profileDraft.domain.trim()
        ? 'Enter a site URL'
        : splitHasNoValues(profileDraft.sourceUrls)
          ? 'Add at least one sitemap or source URL'
          : isGitHub && !profileDraft.githubRepository.trim()
            ? 'Enter a GitHub repository'
            : undefined

    if (!onboarding) {
        return (
            <LemonCard hoverEffect={false} className="p-4">
                <div className="mb-4">
                    <h2 className="m-0">Site and delivery settings</h2>
                    <p className="m-0 mt-1 text-muted">Change this site's sources, boundaries, and delivery path.</p>
                </div>
                <div className="flex flex-col gap-5">
                    <ContentAutopilotSiteFields draft={profileDraft} />
                    <ContentAutopilotSourceFields draft={profileDraft} />
                    <ContentAutopilotDeliveryFields draft={profileDraft} />
                </div>
                <div className="mt-4 flex justify-end">
                    <LemonButton
                        type="primary"
                        onClick={saveProfile}
                        loading={savedProfileLoading}
                        disabledReason={saveDisabledReason}
                    >
                        Save settings
                    </LemonButton>
                </div>
            </LemonCard>
        )
    }

    return (
        <LemonCard hoverEffect={false} className="mx-auto w-full max-w-3xl p-6">
            <ContentAutopilotSetupStepIndicator currentStep={onboardingStep} />
            <div className="my-6 border-t" />

            {onboardingStep === 'site' ? (
                <>
                    <div className="mb-5">
                        <h2 className="m-0">Add a site</h2>
                        <p className="m-0 mt-1 text-muted">
                            PostHog will inspect the public site to fill in the details it can find.
                        </p>
                    </div>
                    <ContentAutopilotSiteFields draft={profileDraft} />
                    <div className="mt-6 flex justify-between">
                        {siteProfiles.length > 0 ? (
                            <LemonButton type="secondary" onClick={cancelOnboarding} disabled={discoveredSiteLoading}>
                                Cancel
                            </LemonButton>
                        ) : (
                            <span />
                        )}
                        <LemonButton
                            type="primary"
                            onClick={discoverSite}
                            loading={discoveredSiteLoading}
                            disabledReason={!profileDraft.domain.trim() ? 'Enter a site URL' : undefined}
                            sideIcon={<IconArrowRight />}
                        >
                            Detect site details
                        </LemonButton>
                    </div>
                </>
            ) : onboardingStep === 'sources' ? (
                <>
                    <div className="mb-5">
                        <h2 className="m-0">Review sources</h2>
                        <p className="m-0 mt-1 text-muted">Confirm where PostHog may research content.</p>
                    </div>
                    {discoveredSite ? (
                        <LemonBanner type={discoveredSite.sitemap_detected ? 'success' : 'warning'} className="mb-4">
                            {discoveredSite.sitemap_detected
                                ? `Detected ${discoveredSite.source_urls.length} sitemap${
                                      discoveredSite.source_urls.length === 1 ? '' : 's'
                                  }.`
                                : discoveredSite.warnings[0]}
                        </LemonBanner>
                    ) : null}
                    <ContentAutopilotSourceFields draft={profileDraft} />
                    <div className="mt-6 flex justify-between">
                        <LemonButton
                            type="secondary"
                            onClick={() => setOnboardingStep('site')}
                            icon={<IconArrowLeft />}
                        >
                            Back
                        </LemonButton>
                        <LemonButton
                            type="primary"
                            onClick={() => setOnboardingStep('delivery')}
                            disabledReason={
                                splitHasNoValues(profileDraft.sourceUrls)
                                    ? 'Add at least one sitemap or source URL'
                                    : undefined
                            }
                            sideIcon={<IconArrowRight />}
                        >
                            Continue
                        </LemonButton>
                    </div>
                </>
            ) : (
                <>
                    <div className="mb-5">
                        <h2 className="m-0">Choose a delivery path</h2>
                        <p className="m-0 mt-1 text-muted">
                            Export Markdown or let PostHog open review-only pull requests. It never merges or publishes.
                        </p>
                    </div>
                    <ContentAutopilotDeliveryFields draft={profileDraft} />
                    <div className="mt-6 flex justify-between">
                        <LemonButton
                            type="secondary"
                            onClick={() => setOnboardingStep('sources')}
                            icon={<IconArrowLeft />}
                            disabled={savedProfileLoading}
                        >
                            Back
                        </LemonButton>
                        <LemonButton
                            type="primary"
                            onClick={saveProfile}
                            loading={savedProfileLoading}
                            disabledReason={saveDisabledReason}
                        >
                            Add site
                        </LemonButton>
                    </div>
                </>
            )}
        </LemonCard>
    )
}

const splitHasNoValues = (value: string): boolean => !value.split('\n').some((line) => line.trim())
