import type { WizardRunApi, WizardRunTaskApi } from '../../../generated/api.schemas'
import { wizardRunIsActive } from '../../../lib/wizardRunDisplay'
import { wizardRunErrorDetails } from '../../../lib/wizardRunErrorCatalog'

export function WizardInstallRunOutcome({
    run,
    tasks,
}: {
    run: WizardRunApi
    tasks: readonly WizardRunTaskApi[]
}): JSX.Element {
    if (wizardRunIsActive(run)) {
        return (
            <p className="mt-3 mb-0 text-xs text-muted">
                You can continue onboarding while the setup agent runs. Follow its progress in the sidebar afterward.
            </p>
        )
    }
    if (run.status === 'failed') {
        const failure =
            run.error_message ||
            tasks.find((task) => task.status === 'failed')?.error_message ||
            wizardRunErrorDetails(run.error_code, null).description
        return (
            <div className="mt-3 text-xs">
                <p className="mb-1 whitespace-pre-wrap break-words text-danger ph-no-capture">{failure}</p>
                <p className="mb-0 text-muted">Review the error and run the setup agent again to retry.</p>
            </div>
        )
    }
    if (run.status === 'cancelled') {
        return (
            <p className="mt-3 mb-0 text-xs text-muted">
                This run was canceled. Run the setup agent again when you're ready.
            </p>
        )
    }
    return (
        <p className="mt-3 mb-0 text-xs">
            {run.environment === 'local'
                ? 'PostHog setup is complete. Review the changes in your local project before committing them.'
                : 'PostHog setup is complete. Review the changes before merging them.'}
        </p>
    )
}
