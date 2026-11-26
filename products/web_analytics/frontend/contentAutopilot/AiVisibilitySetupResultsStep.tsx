import { useActions, useValues } from 'kea'

import { Button, Heading, Text } from '@posthog/quill'

import { AiVisibilityCompetitorReview } from './AiVisibilityCompetitorReview'
import { AiVisibilityFirstResults } from './AiVisibilityFirstResults'
import { AiVisibilitySetupWizardFooter } from './AiVisibilitySetupWizardFooter'
import { contentAutopilotPromptsOverviewLogic } from './contentAutopilotPromptsOverviewLogic'
import { contentAutopilotSetupLogic } from './contentAutopilotSetupLogic'

export const AiVisibilitySetupResultsStep = (): JSX.Element => {
    const { hasCurrentChecks, starting, firstRunDisabledReason } = useValues(contentAutopilotSetupLogic)
    const { setWizardStep, startFirstRun } = useActions(contentAutopilotSetupLogic)
    const { loadPromptSetOverview } = useActions(contentAutopilotPromptsOverviewLogic)
    const hasChecks = hasCurrentChecks

    const finish = (): void => {
        setWizardStep('done')
        loadPromptSetOverview()
    }

    return (
        <div className="flex flex-col gap-4" data-attr="ai-visibility-setup-results">
            {hasChecks ? (
                <>
                    <AiVisibilityFirstResults />
                    <AiVisibilityCompetitorReview />
                </>
            ) : (
                <div>
                    <Heading size="sm" render={<h3 className="m-0" />}>
                        No results yet
                    </Heading>
                    <Text size="sm" variant="muted" render={<p className="m-0 mt-1" />}>
                        Run the first check to see how AI answers see you in a few minutes. Otherwise each engine checks
                        your prompts on its schedule, and the overview fills in as the answers arrive.
                    </Text>
                </div>
            )}
            <AiVisibilitySetupWizardFooter onBack={() => setWizardStep('review')}>
                {hasChecks ? null : (
                    <Button
                        variant="outline"
                        onClick={() => startFirstRun(false)}
                        loading={starting}
                        disabledReason={firstRunDisabledReason}
                        data-attr="ai-visibility-setup-results-run"
                    >
                        Run the first check
                    </Button>
                )}
                <Button
                    variant="primary"
                    onClick={finish}
                    // pinned: data-attr values are API for autocapture dashboards
                    data-attr="ai-visibility-first-results-dismiss"
                >
                    Go to the overview
                </Button>
            </AiVisibilitySetupWizardFooter>
        </div>
    )
}
