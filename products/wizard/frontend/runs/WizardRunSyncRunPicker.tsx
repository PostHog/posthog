import { IconCheck, IconChevronDown, IconCloud, IconLaptop } from '@posthog/icons'
import { LemonButton, LemonMenu, type LemonMenuItems } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import type { WizardRunApi } from '../generated/api.schemas'
import { wizardRunIsActive, wizardRunTerminalLabel, wizardWorkspaceLabel } from '../wizardRunDisplay'

export function WizardRunSyncRunPicker({
    runs,
    activeCount,
    currentRunId,
    onSelect,
    onOpen,
}: {
    runs: readonly WizardRunApi[]
    activeCount: number
    currentRunId: string
    onSelect: (run: WizardRunApi) => void
    onOpen: () => void
}): JSX.Element {
    const currentIndex = runs.findIndex((run) => run.id === currentRunId)
    const items: LemonMenuItems = runs.map((run) => ({
        label: (
            <span className="block min-w-0 text-left ph-no-capture">
                <span className="block truncate font-medium">{wizardWorkspaceLabel(run)}</span>
                <span className="block text-xs text-muted">
                    {wizardRunIsActive(run) ? 'In progress' : wizardRunTerminalLabel(run.status)}
                </span>
                <span className="block truncate text-xs text-muted">
                    {run.program.name} ·{' '}
                    {new Date(run.created_at).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })}
                </span>
            </span>
        ),
        icon: run.environment === 'cloud' ? <IconCloud /> : <IconLaptop />,
        sideIcon: run.id === currentRunId ? <IconCheck aria-label="Selected run" /> : undefined,
        active: run.id === currentRunId,
        onClick: (): void => {
            if (run.id !== currentRunId) {
                onSelect(run)
            }
        },
    }))

    items.push({ label: 'View all runs', to: urls.wizardRuns() })

    return (
        <LemonMenu items={items} matchWidth placement="top-end">
            <LemonButton
                size="xsmall"
                fullWidth
                sideIcon={<IconChevronDown />}
                aria-label={`Switch Wizard run, ${runs.length} recent runs, ${activeCount} active runs`}
                // Keep the analytics selector stable when the picker layout changes.
                data-attr="wizard-run-sync-stack"
                onClick={onOpen}
            >
                <span>{currentIndex >= 0 ? `Run ${currentIndex + 1} of ${runs.length}` : 'Recent runs'}</span>
                {activeCount > 0 && <span className="ml-auto text-muted">{`${activeCount} active`}</span>}
            </LemonButton>
        </LemonMenu>
    )
}
