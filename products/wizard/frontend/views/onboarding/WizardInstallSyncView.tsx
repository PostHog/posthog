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
import { WizardInstallRunArtifacts } from './components/WizardInstallRunArtifacts'
import { WizardInstallRunOutcome } from './components/WizardInstallRunOutcome'
import { WizardInstallRunProgress } from './components/WizardInstallRunProgress'
import type { WizardOnboardingArtifactClickSource } from './onboardingWizardRunLogic'

export function WizardInstallSyncView({
    run,
    tasks,
    artifacts = [],
    now,
    loading = false,
    error = null,
    onRetry,
    onArtifactClick,
}: {
    run: WizardRunApi
    tasks: readonly WizardRunTaskApi[]
    artifacts?: readonly WizardRunArtifactApi[]
    now: number
    loading?: boolean
    error?: string | null
    onRetry?: () => void
    onArtifactClick?: (artifact: WizardRunArtifactApi, source: WizardOnboardingArtifactClickSource) => void
}): JSX.Element {
    return (
        <LemonCard className="p-3" hoverEffect={false} data-attr="wizard-install-sync">
            <div className="flex items-center gap-2">
                <WizardRunStatusIcon status={run.status} />
                <div className="min-w-0 flex-1">
                    <div className="truncate text-sm font-semibold ph-no-capture">{run.program.name}</div>
                    <div className="truncate text-xs text-muted ph-no-capture">
                        {run.status === 'failed' ? 'Setup failed' : wizardRunActivityLabel(run, tasks)}
                    </div>
                </div>
                <span className="shrink-0 text-xs tabular-nums text-muted" translate="no">
                    {formatWizardRunElapsed(wizardRunElapsedSeconds(run, now))}
                </span>
            </div>

            {wizardRunIsActive(run) && <WizardInstallRunProgress run={run} tasks={tasks} />}
            <WizardInstallRunOutcome run={run} tasks={tasks} />
            <WizardInstallRunArtifacts
                run={run}
                artifacts={artifacts}
                loading={loading}
                error={error}
                onArtifactClick={onArtifactClick}
            />
            {error && (
                <div className="mt-3 flex flex-wrap items-center gap-2 text-xs text-danger">
                    <span>{error}</span>
                    <LemonButton size="xsmall" onClick={onRetry} loading={loading} data-attr="wizard-install-retry">
                        Try again
                    </LemonButton>
                </div>
            )}
            <div className="mt-3 truncate text-2xs text-muted ph-no-capture">{wizardWorkspaceLabel(run)}</div>
        </LemonCard>
    )
}
