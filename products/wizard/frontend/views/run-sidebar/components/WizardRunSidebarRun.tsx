import { IconX } from '@posthog/icons'
import { LemonButton, LemonCheckbox } from '@posthog/lemon-ui'

import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import { WizardRunEnvironmentIcon } from '../../../components/run-tags/WizardRunEnvironmentIcon'
import { WizardRunStatusIcon } from '../../../components/run-tags/WizardRunStatusIcon'
import type { WizardRunApi, WizardRunTaskApi } from '../../../generated/api.schemas'
import { wizardRunActivityLabel, wizardWorkspaceLabel } from '../../../lib/wizardRunDisplay'

export function WizardRunSidebarRun({
    run,
    tasks,
    selected,
    onSelect,
    onDismiss,
    onNavigate,
}: {
    run: WizardRunApi
    tasks: readonly WizardRunTaskApi[]
    selected: boolean
    onSelect: (selected: boolean) => void
    onDismiss: () => void
    onNavigate: () => void
}): JSX.Element {
    return (
        <li
            className="flex min-w-0 items-center gap-2 rounded px-2 py-2 hover:bg-fill-highlight-50"
            data-run-id={run.id}
        >
            <LemonCheckbox
                checked={selected}
                onChange={onSelect}
                aria-label={`Select ${run.program.name}`}
                data-attr="wizard-run-sidebar-select"
            />
            <LinkPrimitive
                to={`${urls.wizardRuns()}?run=${encodeURIComponent(run.id)}`}
                onClick={onNavigate}
                className="flex min-w-0 flex-1 items-start gap-2"
                data-attr="wizard-run-sidebar-widget-row"
            >
                <span className="mt-0.5 shrink-0 text-base">
                    <WizardRunStatusIcon status={run.status} />
                </span>
                <span className="min-w-0 flex-1">
                    <span className="block truncate text-xs font-semibold ph-no-capture">{run.program.name}</span>
                    <span className="block truncate text-xs text-muted ph-no-capture">
                        {wizardRunActivityLabel(run, tasks)}
                    </span>
                    <span className="flex min-w-0 items-center gap-1 text-2xs text-muted ph-no-capture">
                        <WizardRunEnvironmentIcon environment={run.environment} />
                        <span className="truncate">{wizardWorkspaceLabel(run)}</span>
                    </span>
                </span>
            </LinkPrimitive>
            <LemonButton
                type="tertiary"
                size="xsmall"
                icon={<IconX />}
                aria-label={`Dismiss ${run.program.name}`}
                tooltip="Dismiss run"
                onClick={onDismiss}
                data-attr="wizard-run-sidebar-dismiss"
            />
        </li>
    )
}
