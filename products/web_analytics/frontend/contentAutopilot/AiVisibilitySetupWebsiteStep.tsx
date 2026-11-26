import { useActions, useValues } from 'kea'

import { LemonBanner, LemonButton, LemonInput, LemonSkeleton } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'

import { AiVisibilitySetupWizardFooter } from './AiVisibilitySetupWizardFooter'
import { contentAutopilotSetupLogic } from './contentAutopilotSetupLogic'

export const AiVisibilitySetupWebsiteStep = (): JSX.Element => {
    const {
        setupContext,
        setupContextLoading,
        setupContextError,
        domain,
        websiteHint,
        startDisabledReason,
        consentMissing,
        starting,
        startError,
    } = useValues(contentAutopilotSetupLogic)
    const { setDomain, loadSetupContext, startSetup } = useActions(contentAutopilotSetupLogic)

    if (setupContextError && !setupContext) {
        return (
            <LemonBanner
                type="error"
                action={{ children: 'Try again', onClick: loadSetupContext, loading: setupContextLoading }}
            >
                Couldn't load setup. Try again, and if it keeps happening contact support.
            </LemonBanner>
        )
    }
    if (!setupContext) {
        return <LemonSkeleton className="h-64 w-full" />
    }

    return (
        <div data-attr="content-autopilot-setup-card">
            <div className="mx-auto flex max-w-xl flex-col gap-5">
                <div>
                    <h3 className="m-0">Set up AI visibility</h3>
                    <p className="m-0 mt-1 text-muted">
                        PostHog reads your site, saves the questions your buyers ask AI assistants and the keywords to
                        track, and checks how often Claude and ChatGPT name or cite you. You review everything it set up
                        before the next run.
                    </p>
                </div>
                {consentMissing ? (
                    <LemonBanner type="warning" data-attr="content-autopilot-setup-consent-banner">
                        Setup needs AI data processing approved for your organization. An admin can approve it in
                        organization settings.
                    </LemonBanner>
                ) : null}
                <LemonField.Pure label="Your website" help={websiteHint ?? undefined}>
                    <LemonInput
                        value={domain}
                        onChange={setDomain}
                        onPressEnter={() => !startDisabledReason && startSetup()}
                        placeholder="example.com"
                        autoFocus
                        data-attr="content-autopilot-setup-domain"
                    />
                </LemonField.Pure>
                {startError ? <LemonBanner type="error">{startError}</LemonBanner> : null}
            </div>
            <AiVisibilitySetupWizardFooter>
                <LemonButton
                    type="primary"
                    onClick={startSetup}
                    loading={starting}
                    disabledReason={startDisabledReason}
                    // pinned: data-attr values are API for autocapture dashboards
                    data-attr="content-autopilot-setup-run-once"
                >
                    Set up and run the first check
                </LemonButton>
            </AiVisibilitySetupWizardFooter>
        </div>
    )
}
