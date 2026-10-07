import { useValues } from 'kea'

import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonButton } from 'lib/lemon-ui/LemonButton'

import { workflowLogic } from '../../workflowLogic'
import type { WorkflowTreeSequence } from './workflowTree'
import { getWorkflowTreeStepRefs } from './workflowTreePresentation'

// A workflow can fail validation on many steps at once, and one button per step turns the banner
// into its own wall of text.
const MAX_LISTED_STEPS = 5

export function HogFlowTreeValidationBanner({ tree }: { tree: WorkflowTreeSequence }): JSX.Element | null {
    const { actionValidationErrorsById } = useValues(workflowLogic)

    const invalidSteps = getWorkflowTreeStepRefs(tree).filter(
        (step) => actionValidationErrorsById[step.actionId]?.valid === false
    )

    if (!invalidSteps.length) {
        return null
    }

    const listed = invalidSteps.slice(0, MAX_LISTED_STEPS)
    const hiddenCount = invalidSteps.length - listed.length

    return (
        <LemonBanner type="error" className="mb-3">
            <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
                <span className="font-semibold">
                    {invalidSteps.length === 1
                        ? 'Fix 1 step before you can enable this workflow'
                        : `Fix ${invalidSteps.length} steps before you can enable this workflow`}
                </span>
                <span className="flex flex-wrap items-center gap-1">
                    {listed.map((step) => (
                        <LemonButton
                            key={step.elementId}
                            type="secondary"
                            size="xsmall"
                            onClick={() => {
                                const target = document.getElementById(step.elementId)
                                target?.scrollIntoView({ block: 'center', behavior: 'smooth' })
                                target?.querySelector('button')?.focus({ preventScroll: true })
                            }}
                            data-attr="workflow-tree-jump-to-invalid-step"
                        >
                            {step.name}
                        </LemonButton>
                    ))}
                    {hiddenCount > 0 && <span className="text-secondary">and {hiddenCount} more</span>}
                </span>
            </div>
        </LemonBanner>
    )
}
