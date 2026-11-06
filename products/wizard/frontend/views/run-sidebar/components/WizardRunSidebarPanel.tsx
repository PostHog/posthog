import { useEffect, useRef, useState } from 'react'

import { LemonButton } from '@posthog/lemon-ui'

import type { WizardRunApi, WizardRunTaskApi } from '../../../generated/api.schemas'
import { WizardRunSidebarRun } from './WizardRunSidebarRun'

export function WizardRunSidebarPanel({
    runs,
    tasksByRunId,
    onDismissRuns,
    onNavigate,
}: {
    runs: WizardRunApi[]
    tasksByRunId: Record<string, readonly WizardRunTaskApi[]>
    onDismissRuns: (runIds: string[]) => void
    onNavigate: () => void
}): JSX.Element {
    const [selectedIds, setSelectedIds] = useState<string[]>([])
    const panelRef = useRef<HTMLDivElement>(null)
    const selectedRuns = runs.filter((run) => selectedIds.includes(run.id))
    useEffect(() => {
        panelRef.current?.focus()
    }, [])

    return (
        <div
            ref={panelRef}
            tabIndex={-1}
            role="dialog"
            aria-label="Wizard runs"
            className="w-80"
            data-attr="wizard-run-sidebar-widget-runs"
        >
            <div className="flex items-center justify-between gap-2 border-b border-primary px-3 py-2">
                <h4 className="mb-0 text-sm">Wizard runs</h4>
                <LemonButton
                    type="tertiary"
                    size="xsmall"
                    onClick={() => onDismissRuns(runs.map((run) => run.id))}
                    data-attr="wizard-run-sidebar-dismiss-all"
                >
                    Dismiss all
                </LemonButton>
            </div>
            <ul className="m-0 max-h-80 list-none overflow-y-auto p-1">
                {runs.map((run) => (
                    <WizardRunSidebarRun
                        key={run.id}
                        run={run}
                        tasks={tasksByRunId[run.id] ?? []}
                        selected={selectedIds.includes(run.id)}
                        onSelect={(selected) =>
                            setSelectedIds((ids) => (selected ? [...ids, run.id] : ids.filter((id) => id !== run.id)))
                        }
                        onDismiss={() => onDismissRuns([run.id])}
                        onNavigate={onNavigate}
                    />
                ))}
            </ul>
            <div className="flex flex-wrap items-center justify-between gap-2 border-t border-primary px-3 py-2">
                <span className="text-2xs text-muted">Dismissing a run doesn't stop it.</span>
                {selectedRuns.length > 0 && (
                    <LemonButton
                        type="secondary"
                        size="xsmall"
                        onClick={() => {
                            onDismissRuns(selectedRuns.map((run) => run.id))
                            setSelectedIds([])
                        }}
                        data-attr="wizard-run-sidebar-dismiss-selected"
                    >{`Dismiss selected (${selectedRuns.length})`}</LemonButton>
                )}
            </div>
        </div>
    )
}
