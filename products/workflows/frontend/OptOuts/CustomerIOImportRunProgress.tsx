import { IconCheckCircle, IconCircleDashed, IconWarning } from '@posthog/icons'
import { Spinner } from '@posthog/lemon-ui'

import type {
    ImportStepProgressApi,
    ImportStepStatusEnumApi,
    ProviderImportRunApi,
} from 'products/messaging/frontend/generated/api.schemas'

const STEP_ICONS: Record<ImportStepStatusEnumApi, JSX.Element> = {
    pending: <IconCircleDashed className="text-muted text-base shrink-0" />,
    running: <Spinner className="text-base shrink-0" />,
    completed: <IconCheckCircle className="text-success text-base shrink-0" />,
    failed: <IconWarning className="text-danger text-base shrink-0" />,
}

function stepCounts(step: ImportStepProgressApi): string {
    if (step.status === 'pending') {
        return 'Not started'
    }
    return `${step.processed.toLocaleString()} read · ${step.imported.toLocaleString()} new or changed`
}

export function CustomerIOImportRunProgress({ run }: { run: ProviderImportRunApi }): JSX.Element {
    return (
        <ul className="flex flex-col gap-3 m-0 p-0 list-none" data-attr="customerio-import-run-progress">
            {run.steps.map((step) => (
                <li key={step.key} className="flex flex-col gap-1">
                    <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1">
                        <span className="flex items-center gap-2 font-medium">
                            {STEP_ICONS[step.status]}
                            <span>{step.label}</span>
                        </span>
                        <span className="text-xs text-secondary" translate="no">
                            {stepCounts(step)}
                        </span>
                    </div>
                    {step.last_error && (
                        <div className={step.status === 'failed' ? 'text-xs text-danger' : 'text-xs text-warning'}>
                            {step.status === 'failed' ? step.last_error : `Retrying after an error: ${step.last_error}`}
                        </div>
                    )}
                    {step.warnings.length > 0 && (
                        <div className="text-xs text-secondary">{step.warnings.join(' ')}</div>
                    )}
                </li>
            ))}
        </ul>
    )
}
