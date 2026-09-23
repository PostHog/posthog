import { IconChevronDown, IconCloud, IconLaptop } from '@posthog/icons'
import { LemonMenu, type LemonMenuItems } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import type { WizardRunApi } from '../generated/api.schemas'
import { wizardWorkspaceLabel } from '../wizardRunDisplay'

export function WizardRunSyncRunPicker({
    runs,
    activeCount,
    currentRunId,
    onSelect,
}: {
    runs: readonly WizardRunApi[]
    activeCount: number
    currentRunId: string
    onSelect: (run: WizardRunApi) => void
}): JSX.Element {
    const items: LemonMenuItems = runs
        .filter((run) => run.id !== currentRunId)
        .map((run) => ({
            label: (
                <span className="block min-w-0 text-left ph-no-capture">
                    <span className="block truncate font-medium">{run.program.name}</span>
                    <span className="block truncate text-xs text-muted">
                        {wizardWorkspaceLabel(run)} ·{' '}
                        {new Date(run.created_at).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })}
                    </span>
                </span>
            ),
            icon: run.environment === 'cloud' ? <IconCloud /> : <IconLaptop />,
            onClick: (): void => onSelect(run),
        }))

    if (activeCount > runs.length) {
        items.push({ label: 'View all runs', to: urls.wizardRuns() })
    }

    return (
        <div className="group relative h-8" data-attr="wizard-run-sync-stack">
            <div
                aria-hidden="true"
                className="absolute inset-x-8 top-0 h-6 rounded-t-xl border border-primary bg-surface-secondary motion-safe:transition-transform motion-safe:group-hover:-translate-y-1 motion-safe:group-focus-within:-translate-y-1"
            />
            <div
                aria-hidden="true"
                className="absolute inset-x-5 top-1 h-6 rounded-t-xl border border-primary bg-surface-secondary motion-safe:transition-transform motion-safe:group-hover:-translate-y-0.5 motion-safe:group-focus-within:-translate-y-0.5"
            />
            <LemonMenu items={items} matchWidth placement="top-end" trigger="hover">
                <button
                    type="button"
                    className="absolute inset-x-3 bottom-0 flex h-6 cursor-pointer items-center justify-between rounded-t-lg border border-b-0 border-primary bg-surface-primary px-3 text-xs text-secondary hover:bg-fill-highlight-50 focus-visible:outline focus-visible:outline-accent"
                    aria-label={`Switch Wizard run, ${activeCount} active runs`}
                >
                    <span>{activeCount} active runs</span>
                    <span className="flex items-center gap-1">
                        Switch run <IconChevronDown className="rotate-180" />
                    </span>
                </button>
            </LemonMenu>
        </div>
    )
}
