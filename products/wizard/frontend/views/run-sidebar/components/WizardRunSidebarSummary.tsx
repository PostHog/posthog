import { IconSparkles } from '@posthog/icons'

import { cn } from 'lib/utils/css-classes'

import { WizardRunEnvironmentIcon } from '../../../components/run-tags/WizardRunEnvironmentIcon'
import { WizardRunStatusIcon } from '../../../components/run-tags/WizardRunStatusIcon'
import type { WizardRunApi, WizardRunTaskApi } from '../../../generated/api.schemas'
import { wizardRunActivityLabel, wizardRunIsActive, wizardWorkspaceLabel } from '../../../lib/wizardRunDisplay'

export function WizardRunSidebarSummary({
    runs,
    tasks,
    hovered,
}: {
    runs: WizardRunApi[]
    tasks: readonly WizardRunTaskApi[]
    hovered: boolean
}): JSX.Element {
    const run = runs[0]
    const counts: { status: WizardRunApi['status']; count: number; label: string }[] = [
        { status: 'running', count: runs.filter(wizardRunIsActive).length, label: 'running' },
        { status: 'failed', count: runs.filter((run) => run.status === 'failed').length, label: 'failed' },
        { status: 'completed', count: runs.filter((run) => run.status === 'completed').length, label: 'completed' },
        { status: 'cancelled', count: runs.filter((run) => run.status === 'cancelled').length, label: 'canceled' },
    ]
    return (
        <span className="flex w-full min-w-0 items-center gap-2">
            <span className="shrink-0 text-base">
                {runs.length > 1 ? <IconSparkles /> : <WizardRunStatusIcon status={run.status} />}
            </span>
            <span className="min-w-0 flex-1 text-left">
                {runs.length > 1 ? (
                    <>
                        <span className="block truncate text-xs font-semibold">{`Wizard runs (${runs.length})`}</span>
                        <span className="flex flex-wrap items-center gap-x-2 gap-y-0.5 text-xs text-muted">
                            {counts
                                .filter(({ count }) => count > 0)
                                .map(({ status, count, label }) => (
                                    <span
                                        key={status}
                                        className="flex items-center gap-0.5"
                                        title={`${count} ${label}`}
                                    >
                                        <WizardRunStatusIcon status={status} />
                                        <span>{count}</span>
                                        <span className="sr-only">{label}</span>
                                    </span>
                                ))}
                        </span>
                    </>
                ) : (
                    <>
                        <span className="flex min-w-0 items-center gap-1">
                            <span className="relative h-4 min-w-0 flex-1 overflow-hidden">
                                <span
                                    className={cn(
                                        'flex flex-col transition-transform duration-200 ease-out motion-reduce:transition-none group-hover/wizard-run:-translate-y-4 group-focus-within/wizard-run:-translate-y-4',
                                        hovered ? '-translate-y-4' : 'translate-y-0'
                                    )}
                                >
                                    <span className="h-4 truncate text-xs font-semibold leading-4 ph-no-capture">
                                        {run.program.name}
                                    </span>
                                    <span className="h-4 truncate text-xs font-semibold leading-4 ph-no-capture">
                                        {wizardRunActivityLabel(run, tasks)}
                                    </span>
                                </span>
                            </span>
                        </span>
                        <span className="flex min-w-0 items-center gap-1 text-2xs text-muted ph-no-capture">
                            <WizardRunEnvironmentIcon environment={run.environment} />
                            <span className="truncate">{wizardWorkspaceLabel(run)}</span>
                        </span>
                    </>
                )}
            </span>
        </span>
    )
}
