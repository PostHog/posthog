import { LemonButton, LemonCard } from '@posthog/lemon-ui'

import { WizardRunStatusIcon } from '../../components/run-tags/WizardRunStatusIcon'
import type { WizardRunApi, WizardRunArtifactApi, WizardRunTaskApi } from '../../generated/api.schemas'
import {
    formatWizardRunElapsed,
    wizardRunActivityLabel,
    wizardRunElapsedSeconds,
    wizardRunIsActive,
    wizardWorkspaceLabel,
} from '../../lib/wizardRunDisplay'
import { wizardRunErrorDetails } from '../../lib/wizardRunErrorCatalog'
import { WizardInstallRunArtifacts } from '../onboarding/components/WizardInstallRunArtifacts'
import { WizardSpendAuditProgress } from './WizardSpendAuditProgress'
import { WizardSpendAuditResults } from './WizardSpendAuditResults'

function AuditOutcome({ run, tasks }: { run: WizardRunApi; tasks: readonly WizardRunTaskApi[] }): JSX.Element | null {
    if (wizardRunIsActive(run)) {
        return (
            <p className="mt-3 mb-0 text-xs text-muted">
                You can close this window. The audit keeps running, and the result shows up here and in Wizard runs.
            </p>
        )
    }
    if (run.status === 'failed') {
        const details = wizardRunErrorDetails(run.error_code, null)
        const failure =
            run.error_message || tasks.find((task) => task.status === 'failed')?.error_message || details.description
        return (
            <div className="mt-3 text-xs">
                <p className="mb-1 whitespace-pre-wrap break-words text-danger ph-no-capture">{failure}</p>
                <p className="mb-0 text-muted">{details.resolution ?? 'Review the error and run the audit again.'}</p>
            </div>
        )
    }
    if (run.status === 'cancelled') {
        return <p className="mt-3 mb-0 text-xs text-muted">This audit was canceled. Run it again when you're ready.</p>
    }
    // A finished audit shows its results, notebook and pull request in WizardSpendAuditResults.
    return null
}

export function WizardSpendAuditRunView({
    run,
    tasks,
    artifacts,
    now,
    loading,
    error,
    onRetry,
}: {
    run: WizardRunApi
    tasks: readonly WizardRunTaskApi[]
    artifacts: readonly WizardRunArtifactApi[]
    now: number
    loading: boolean
    error: string | null
    onRetry: () => void
}): JSX.Element {
    return (
        <LemonCard className="p-3" hoverEffect={false} data-attr="wizard-spend-audit-run">
            <div className="flex items-center gap-2">
                <WizardRunStatusIcon status={run.status} />
                <div className="min-w-0 flex-1">
                    <div className="truncate text-sm font-semibold ph-no-capture">{run.program.name}</div>
                    <div className="truncate text-xs text-muted ph-no-capture">
                        {run.status === 'failed' ? 'Audit failed' : wizardRunActivityLabel(run, tasks)}
                    </div>
                </div>
                <span className="shrink-0 text-xs tabular-nums text-muted" translate="no">
                    {formatWizardRunElapsed(wizardRunElapsedSeconds(run, now))}
                </span>
            </div>

            {run.status !== 'completed' && <WizardSpendAuditProgress run={run} tasks={tasks} />}
            <AuditOutcome run={run} tasks={tasks} />
            {run.status === 'completed' ? (
                <WizardSpendAuditResults run={run} artifacts={artifacts} />
            ) : (
                <WizardInstallRunArtifacts run={run} artifacts={artifacts} loading={loading} error={error} />
            )}
            {error && (
                <div className="mt-3 flex flex-wrap items-center gap-2 text-xs text-danger">
                    <span>{error}</span>
                    <LemonButton size="xsmall" onClick={onRetry} loading={loading} data-attr="wizard-spend-audit-retry">
                        Try again
                    </LemonButton>
                </div>
            )}
            <div className="mt-3 truncate text-2xs text-muted ph-no-capture">{wizardWorkspaceLabel(run)}</div>
        </LemonCard>
    )
}
