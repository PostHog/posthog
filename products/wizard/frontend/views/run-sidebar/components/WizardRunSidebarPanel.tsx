import { useEffect, useRef } from 'react'

import { LemonButton } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import type { WizardDetectedWarehouseSourceApi, WizardRunApi, WizardRunTaskApi } from '../../../generated/api.schemas'
import { WizardDetectedSources } from './WizardDetectedSources'
import { WizardRunSidebarRun } from './WizardRunSidebarRun'

export function WizardRunSidebarPanel({
    runs,
    tasksByRunId,
    onDismissRuns,
    onNavigate,
    detectedSources = [],
    onDetectedSourceClick,
}: {
    runs: WizardRunApi[]
    tasksByRunId: Record<string, readonly WizardRunTaskApi[]>
    onDismissRuns: (runIds: string[]) => void
    onNavigate: () => void
    detectedSources?: WizardDetectedWarehouseSourceApi[]
    onDetectedSourceClick?: (sourceType: string) => void
}): JSX.Element {
    const panelRef = useRef<HTMLDivElement>(null)
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
                {runs.length > 0 && (
                    <LemonButton
                        type="tertiary"
                        size="xsmall"
                        onClick={() => onDismissRuns(runs.map((run) => run.id))}
                        data-attr="wizard-run-sidebar-dismiss-all"
                    >
                        Dismiss all
                    </LemonButton>
                )}
            </div>
            {runs.length === 0 && (
                <p className="mb-0 px-3 py-2 text-sm text-muted">
                    No recent runs. Wizard is a setup agent that installs PostHog in your codebase and opens a pull
                    request.
                </p>
            )}
            <ul className="m-0 max-h-80 list-none overflow-y-auto p-1 empty:hidden">
                {runs.map((run) => (
                    <WizardRunSidebarRun
                        key={run.id}
                        run={run}
                        tasks={tasksByRunId[run.id] ?? []}
                        onDismiss={() => onDismissRuns([run.id])}
                        onNavigate={onNavigate}
                    />
                ))}
            </ul>
            {detectedSources.length > 0 && onDetectedSourceClick && (
                <WizardDetectedSources
                    sources={detectedSources}
                    onSourceClick={(sourceType) => {
                        onDetectedSourceClick(sourceType)
                        onNavigate()
                    }}
                />
            )}
            <div className="flex flex-wrap items-center justify-between gap-2 border-t border-primary px-3 py-2">
                {runs.length > 0 ? (
                    <span className="text-2xs text-muted">Dismissing a run doesn't stop it.</span>
                ) : (
                    <LemonButton
                        type="tertiary"
                        size="xsmall"
                        to={urls.wizardRuns()}
                        onClick={onNavigate}
                        data-attr="wizard-run-sidebar-view-all"
                    >
                        View all runs
                    </LemonButton>
                )}
            </div>
        </div>
    )
}
