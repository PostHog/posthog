import { IconCopy, IconEllipsis, IconListCheck, IconRefresh, IconStopFilled } from '@posthog/icons'
import { LemonButton, LemonMenu } from '@posthog/lemon-ui'

import type { LemonMenuItems } from 'lib/lemon-ui/LemonMenu'

import type { WizardRunApi } from '../generated/api.schemas'
import { wizardRunIsActive } from '../wizardRunDisplay'

export function WizardRunActionsMenu({
    run,
    refreshing,
    cancelling,
    onView,
    onRefresh,
    onCopyRunId,
    onCancel,
}: {
    run: WizardRunApi
    refreshing: boolean
    cancelling: boolean
    onView: (run: WizardRunApi) => void
    onRefresh: (run: WizardRunApi) => void
    onCopyRunId: (runId: string) => void
    onCancel: (run: WizardRunApi) => void
}): JSX.Element {
    const items: LemonMenuItems = [
        {
            items: [
                {
                    label: 'View run details',
                    icon: <IconListCheck />,
                    onClick: () => onView(run),
                },
                {
                    label: 'Refresh status',
                    icon: <IconRefresh />,
                    disabledReason: refreshing ? 'Refreshing…' : null,
                    onClick: () => onRefresh(run),
                },
                {
                    label: 'Copy run ID',
                    icon: <IconCopy />,
                    onClick: () => onCopyRunId(run.id),
                },
            ],
        },
        wizardRunIsActive(run) && {
            items: [
                {
                    label: 'Cancel run',
                    icon: <IconStopFilled />,
                    status: 'danger',
                    disabledReason: cancelling ? 'Canceling…' : null,
                    onClick: () => onCancel(run),
                },
            ],
        },
    ]

    return (
        <LemonMenu items={items} placement="bottom-end" className="min-w-56">
            <LemonButton
                type="tertiary"
                size="small"
                icon={<IconEllipsis />}
                aria-label={`More options for ${run.program.name}`}
                onClick={(event) => event.stopPropagation()}
            />
        </LemonMenu>
    )
}
