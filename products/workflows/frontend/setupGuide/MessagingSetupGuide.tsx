import { useActions, useValues } from 'kea'

import { IconCheckCircle, IconCircleDashed } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { LemonCard } from 'lib/lemon-ui/LemonCard'

import type { MessagingNavTabKey } from '../messagingTabs'
import { SETUP_GUIDE_STEP_LABELS, SETUP_GUIDE_STEP_TABS } from './setupGuideSteps'
import { workflowsSetupGuideLogic } from './workflowsSetupGuideLogic'

/** The messaging setup checklist. Each step opens the real setup page, so people learn where things live. */
export function MessagingSetupGuide({ linkFor }: { linkFor: (tab: MessagingNavTabKey) => string }): JSX.Element | null {
    const { steps, showGuide, completedCount, nextStep } = useValues(workflowsSetupGuideLogic)
    const { hideGuide, stepClicked } = useActions(workflowsSetupGuideLogic)

    if (!showGuide || !steps) {
        return null
    }

    return (
        <LemonCard hoverEffect={false} className="mb-4 p-4" data-attr="messaging-setup-guide">
            <div className="flex flex-wrap items-center justify-between gap-2">
                <h3 className="mb-0 text-base font-semibold">Set up messaging</h3>
                <div className="flex items-center gap-2">
                    <span className="text-secondary text-sm">{`${completedCount} of ${steps.length} done`}</span>
                    <LemonButton
                        size="small"
                        type="tertiary"
                        onClick={hideGuide}
                        data-attr="messaging-setup-guide-hide"
                    >
                        Hide guide
                    </LemonButton>
                </div>
            </div>
            <div className="flex flex-wrap gap-2 mt-3">
                {steps.map((step) => {
                    const tab = SETUP_GUIDE_STEP_TABS[step.key]
                    return (
                        <LemonButton
                            key={step.key}
                            type="secondary"
                            size="small"
                            active={step.key === nextStep}
                            icon={step.done ? <IconCheckCircle className="text-success" /> : <IconCircleDashed />}
                            to={tab ? linkFor(tab) : undefined}
                            onClick={() => stepClicked(step.key)}
                            data-attr={`messaging-setup-guide-step-${step.key}`}
                        >
                            {SETUP_GUIDE_STEP_LABELS[step.key]}
                        </LemonButton>
                    )
                })}
            </div>
        </LemonCard>
    )
}
