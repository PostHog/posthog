import type { ReactNode } from 'react'

import { IconCheckCircle, IconCloud, IconExpand45, IconLaptop, IconWarning, IconX } from '@posthog/icons'
import { LemonButton, LemonMenu, Spinner } from '@posthog/lemon-ui'

import { cn } from 'lib/utils/css-classes'
import { formatElapsed } from 'scenes/onboarding/shared/wizard-sync/helpers'

import type { WizardRunApi, WizardRunTaskApi } from '../generated/api.schemas'
import type { WizardRunProgressState } from '../wizardRunDisplay'
import {
    wizardRunCurrentState,
    wizardRunProgressState,
    wizardRunStagePosition,
    wizardWorkspaceLabel,
} from '../wizardRunDisplay'

function RunStatusGlyph({ status }: { status: WizardRunApi['status'] }): JSX.Element {
    if (status === 'completed') {
        return <IconCheckCircle className="shrink-0 text-xl text-success" />
    }
    if (status === 'failed' || status === 'cancelled') {
        return <IconWarning className="shrink-0 text-xl text-danger" />
    }
    return <Spinner className="shrink-0 text-xl text-accent" textColored />
}

function pipClass(state: WizardRunProgressState): string {
    switch (state) {
        case 'complete':
            return 'bg-success'
        case 'active':
            return 'bg-accent animate-pulse'
        case 'failed':
            return 'bg-danger'
        default:
            return 'bg-border'
    }
}

export function WizardRunSyncCard({
    run,
    tasks,
    elapsedSeconds,
    onExpand,
    onExpandIcon,
    onClose,
    onHide,
    runPicker,
}: {
    run: WizardRunApi
    tasks: readonly WizardRunTaskApi[]
    elapsedSeconds: number
    onExpand: () => void
    onExpandIcon: () => void
    onClose: () => void
    onHide: () => void
    runPicker?: ReactNode
}): JSX.Element {
    const currentTask =
        run.status === 'running' && wizardRunStagePosition(run) === 2
            ? tasks.find((task) => task.status === 'running')
            : undefined
    const currentState = wizardRunCurrentState(run)
    const states = [0, 1, 2, 3].map((step) => wizardRunProgressState(run, step))
    const completed = states.filter((state) => state === 'complete').length
    const workspace = wizardWorkspaceLabel(run)

    return (
        <div
            className="w-[340px] max-w-full overflow-hidden rounded-xl border border-primary bg-surface-primary shadow-xl shadow-black/10"
            role="status"
            aria-live="polite"
            data-attr="wizard-run-sync-card"
        >
            {runPicker && <div className="border-b border-primary px-2 py-1">{runPicker}</div>}
            <button
                type="button"
                onClick={onExpand}
                aria-label="Expand Wizard run details"
                className="flex w-full cursor-pointer flex-col gap-2.5 px-3.5 py-3 text-left transition-colors hover:bg-fill-highlight-50"
            >
                <div className="flex items-center gap-2.5">
                    <RunStatusGlyph status={run.status} />
                    <div className="min-w-0 flex-1">
                        <p
                            className={cn(
                                'm-0 truncate text-sm font-semibold ph-no-capture',
                                run.status === 'completed'
                                    ? 'text-success'
                                    : run.status === 'failed' || run.status === 'cancelled'
                                      ? 'text-danger'
                                      : 'text-accent'
                            )}
                            title={currentTask?.name}
                        >
                            {currentTask?.name ?? currentState}
                        </p>
                        <p className="m-0 truncate text-xs text-muted">
                            {currentTask ? currentState : run.program.name}
                        </p>
                    </div>
                    <span className="shrink-0 text-xs tabular-nums text-muted">{formatElapsed(elapsedSeconds)}</span>
                </div>
                <div className="flex items-center gap-2">
                    <div className="flex w-full items-center gap-1" aria-hidden="true">
                        {states.map((state, index) => (
                            <span key={index} className={cn('h-1 flex-1 rounded-full', pipClass(state))} />
                        ))}
                    </div>
                    <span className="shrink-0 text-xs tabular-nums text-muted">
                        {completed}/{states.length}
                    </span>
                </div>
            </button>
            <div className="flex items-center justify-between gap-2 border-t border-primary px-3.5 py-2">
                <span className="flex min-w-0 items-center gap-1 text-xs text-muted ph-no-capture">
                    {run.environment === 'cloud' ? (
                        <IconCloud className="shrink-0" />
                    ) : (
                        <IconLaptop className="shrink-0" />
                    )}
                    <span className="shrink-0">{run.environment === 'cloud' ? 'Cloud run' : 'Local run'}</span>
                    <span aria-hidden="true">·</span>
                    <span className="truncate" title={workspace}>
                        {workspace}
                    </span>
                </span>
                <div className="flex shrink-0 items-center gap-1">
                    <LemonButton
                        size="xsmall"
                        icon={<IconExpand45 />}
                        onClick={onExpandIcon}
                        tooltip="See all the details"
                        aria-label="Expand"
                    />
                    <LemonMenu
                        items={[
                            { label: 'Close', onClick: onClose },
                            { label: "Don't show this run again", onClick: onHide },
                        ]}
                        placement="top-end"
                    >
                        <LemonButton
                            size="xsmall"
                            icon={<IconX />}
                            tooltip="Close options"
                            aria-label="Close options"
                        />
                    </LemonMenu>
                </div>
            </div>
        </div>
    )
}
