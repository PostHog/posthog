import { IconX } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import { WizardRunEnvironmentIcon } from '../../../components/run-tags/WizardRunEnvironmentIcon'
import { WizardRunStatusIcon } from '../../../components/run-tags/WizardRunStatusIcon'
import type { WizardRunApi, WizardRunTaskApi } from '../../../generated/api.schemas'
import {
    wizardRunActivityLabel,
    wizardRunIsActive,
    wizardRunTaskCounts,
    wizardWorkspaceLabel,
} from '../../../lib/wizardRunDisplay'

export function WizardRunSidebarRun({
    run,
    tasks,
    onDismiss,
    onNavigate,
}: {
    run: WizardRunApi
    tasks: readonly WizardRunTaskApi[]
    onDismiss: () => void
    onNavigate: () => void
}): JSX.Element {
    const { completed, total } = wizardRunTaskCounts(tasks)
    return (
        <li
            className="flex min-w-0 items-start gap-2 rounded px-2 py-2 hover:bg-fill-highlight-50"
            data-run-id={run.id}
        >
            <LinkPrimitive
                to={`${urls.wizardRuns()}?run=${encodeURIComponent(run.id)}`}
                onClick={onNavigate}
                className="grid min-w-0 flex-1 grid-cols-[1rem_minmax(0,1fr)] items-center gap-x-2"
                data-attr="wizard-run-sidebar-widget-row"
            >
                <span className="flex justify-center text-base">
                    <WizardRunStatusIcon status={run.status} />
                </span>
                <span className="truncate text-xs font-semibold ph-no-capture">{run.program.name}</span>
                <span aria-hidden />
                <span className="flex min-w-0 gap-1 text-xs text-muted ph-no-capture">
                    <span className="truncate">{wizardRunActivityLabel(run, tasks)}</span>
                    {wizardRunIsActive(run) && total > 0 && (
                        <span className="shrink-0">{`· ${completed} of ${total} ${total === 1 ? 'step' : 'steps'}`}</span>
                    )}
                </span>
                <span className="flex justify-center text-xs text-muted">
                    <WizardRunEnvironmentIcon environment={run.environment} />
                </span>
                <span className="truncate text-2xs text-muted ph-no-capture">{wizardWorkspaceLabel(run)}</span>
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
