import { useActions, useValues } from 'kea'

import { IconArrowLeft, IconArrowRight } from '@posthog/icons'
import { LemonButton, LemonCard } from '@posthog/lemon-ui'

import { GuidedWizardStep, GuidedWizardStepper } from 'lib/components/GuidedWizard/GuidedWizardStepper'

import { AiVisibilityBanner } from './AiVisibilityBanner'
import { ContentAutopilotOnboardingStep, contentAutopilotLogic } from './contentAutopilotLogic'
import { ContentAutopilotSiteFields } from './ContentAutopilotSiteFields'
import { ContentAutopilotSiteSettingsCard } from './ContentAutopilotSiteSettingsCard'
import { ContentAutopilotSourceFields } from './ContentAutopilotSourceFields'

const SETUP_STEPS: GuidedWizardStep<ContentAutopilotOnboardingStep>[] = [
    { step: 'site', label: 'Site' },
    { step: 'sources', label: 'Sources' },
]

export const ContentAutopilotSetup = ({ onboarding = false }: { onboarding?: boolean }): JSX.Element => {
    const {
        siteProfiles,
        profile,
        profileDraft,
        onboardingStep,
        discoveredSite,
        discoveredSiteLoading,
        savedProfileLoading,
        deletedProfileLoading,
    } = useValues(contentAutopilotLogic)
    const { cancelOnboarding, deleteProfile, discoverSite, saveProfile, setOnboardingStep } =
        useActions(contentAutopilotLogic)
    const saveDisabledReason = !profileDraft.domain.trim()
        ? 'Enter a site URL'
        : splitHasNoValues(profileDraft.sourceUrls)
          ? 'Add at least one sitemap or source URL'
          : undefined

    if (!onboarding) {
        return (
            <ContentAutopilotSiteSettingsCard
                siteLabel={profile ? profile.name || profile.domain : null}
                draft={profileDraft}
                deleting={deletedProfileLoading}
                saving={savedProfileLoading}
                saveDisabledReason={saveDisabledReason}
                onDelete={() => profile && deleteProfile(profile.id)}
                onSave={saveProfile}
            />
        )
    }

    return (
        <LemonCard hoverEffect={false} className="mx-auto w-full max-w-3xl p-6">
            <GuidedWizardStepper steps={SETUP_STEPS} currentStep={onboardingStep} aria-label="Setup progress" />
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
            ) : (
                <>
                    <div className="mb-5">
                        <h2 className="m-0">Review sources</h2>
                        <p className="m-0 mt-1 text-muted">Confirm where PostHog may research content.</p>
                    </div>
                    {discoveredSite ? (
                        <AiVisibilityBanner
                            type={discoveredSite.sitemap_detected ? 'success' : 'warning'}
                            className="mb-4"
                        >
                            {discoveredSite.sitemap_detected
                                ? `Detected ${discoveredSite.source_urls.length} sitemap${
                                      discoveredSite.source_urls.length === 1 ? '' : 's'
                                  }.`
                                : discoveredSite.warnings[0]}
                        </AiVisibilityBanner>
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
