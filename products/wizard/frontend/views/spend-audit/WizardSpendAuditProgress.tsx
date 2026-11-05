import { WizardRunProgressStateIcon } from '../../components/run-tags/WizardRunProgressStateIcon'
import type { WizardRunApi, WizardRunTaskApi } from '../../generated/api.schemas'
import { WIZARD_SPEND_AUDIT_STEPS, wizardSpendAuditStepStates } from './wizardSpendAuditSteps'

export function WizardSpendAuditProgress({
    run,
    tasks,
}: {
    run: WizardRunApi
    tasks: readonly WizardRunTaskApi[]
}): JSX.Element {
    const states = wizardSpendAuditStepStates(run, tasks)
    return (
        <ul className="mt-3 mb-0 list-none space-y-1 p-0" data-attr="wizard-spend-audit-steps">
            {WIZARD_SPEND_AUDIT_STEPS.map((step) => (
                <li
                    key={step.key}
                    className="flex items-center gap-2 text-xs"
                    data-attr={`wizard-spend-audit-step-${step.key}`}
                >
                    <WizardRunProgressStateIcon state={states[step.key]} />
                    <span className={states[step.key] === 'pending' ? 'text-muted' : undefined}>{step.label}</span>
                </li>
            ))}
        </ul>
    )
}
