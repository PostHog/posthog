import { useActions, useValues } from 'kea'
import { useId } from 'react'

import { Button, Field, FieldDescription, FieldLabel, Heading, Input, Skeleton, Text } from '@posthog/quill'

import { AiVisibilityBanner } from './AiVisibilityBanner'
import { AiVisibilitySetupWizardFooter } from './AiVisibilitySetupWizardFooter'
import { contentAutopilotSetupLogic } from './contentAutopilotSetupLogic'

export const AiVisibilitySetupWebsiteStep = (): JSX.Element => {
    const id = useId()
    const { setupContext, domain, websiteHint, startDisabledReason, consentMissing, starting, startError } =
        useValues(contentAutopilotSetupLogic)
    const { setDomain, startSetup } = useActions(contentAutopilotSetupLogic)

    if (!setupContext) {
        return <Skeleton className="h-64 w-full" />
    }

    return (
        <div data-attr="content-autopilot-setup-card">
            <div className="mx-auto flex max-w-xl flex-col gap-5">
                <div>
                    <Heading size="sm" render={<h3 className="m-0" />}>
                        Set up AI visibility
                    </Heading>
                    <Text size="sm" variant="muted" render={<p className="m-0 mt-1" />}>
                        PostHog reads your site, saves the questions your buyers ask AI assistants and the keywords to
                        track, and checks how often Claude and ChatGPT name or cite you. You review everything it set up
                        before the next run.
                    </Text>
                </div>
                {consentMissing ? (
                    <AiVisibilityBanner type="warning" data-attr="content-autopilot-setup-consent-banner">
                        Setup needs AI data processing approved for your organization. An admin can approve it in
                        organization settings.
                    </AiVisibilityBanner>
                ) : null}
                <Field>
                    <FieldLabel htmlFor={`${id}-domain`}>Your website</FieldLabel>
                    <Input
                        id={`${id}-domain`}
                        value={domain}
                        onChange={(event) => setDomain(event.target.value)}
                        onKeyDown={(event) => {
                            if (event.key === 'Enter' && !startDisabledReason) {
                                startSetup()
                            }
                        }}
                        placeholder="example.com"
                        autoFocus
                        data-attr="content-autopilot-setup-domain"
                    />
                    {websiteHint ? <FieldDescription>{websiteHint}</FieldDescription> : null}
                </Field>
                {startError ? <AiVisibilityBanner type="error">{startError}</AiVisibilityBanner> : null}
            </div>
            <AiVisibilitySetupWizardFooter>
                <Button
                    variant="primary"
                    onClick={startSetup}
                    loading={starting}
                    disabledReason={startDisabledReason}
                    // pinned: data-attr values are API for autocapture dashboards
                    data-attr="content-autopilot-setup-run-once"
                >
                    Set up and run the first check
                </Button>
            </AiVisibilitySetupWizardFooter>
        </div>
    )
}
