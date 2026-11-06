import { useActions, useValues } from 'kea'

import { LemonBanner } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { SETUP_GUIDE_STEP_LABELS, SETUP_GUIDE_STEP_TABS } from './setupGuideSteps'
import { workflowsSetupGuideLogic } from './workflowsSetupGuideLogic'

/** One line on the workflows list that keeps the next messaging setup step in view until setup is done. */
export function MessagingSetupReminderBanner(): JSX.Element | null {
    const { showMessagingReminder, nextStep, completedCount, steps } = useValues(workflowsSetupGuideLogic)
    const { hideGuide, stepClicked } = useActions(workflowsSetupGuideLogic)

    if (!showMessagingReminder || !nextStep || !steps) {
        return null
    }
    const tab = SETUP_GUIDE_STEP_TABS[nextStep]

    return (
        <LemonBanner
            type="info"
            className="mb-4"
            onClose={hideGuide}
            action={{
                children: 'Continue setup',
                to: tab ? urls.workflows(tab) : undefined,
                onClick: () => stepClicked(nextStep),
                'data-attr': 'messaging-setup-reminder-continue',
            }}
        >
            {`Messaging setup: ${completedCount} of ${steps.length} done. Next: ${SETUP_GUIDE_STEP_LABELS[nextStep].toLowerCase()}.`}
        </LemonBanner>
    )
}
