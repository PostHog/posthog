import { BindLogic, useActions, useValues } from 'kea'

import { IconPlus, IconTrash } from '@posthog/icons'
import { LemonButton, LemonSwitch, LemonTable } from '@posthog/lemon-ui'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { XRayHog } from 'lib/components/hedgehogs'
import { ProductIntroduction } from 'lib/components/ProductIntroduction/ProductIntroduction'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

import type { VisionActionApi } from '../../generated/api.schemas'
import { visionActionsLogic } from '../visionActionsLogic'

const FREQ_LABELS: Record<string, string> = {
    HOURLY: 'Hourly',
    DAILY: 'Daily',
    WEEKLY: 'Weekly',
    MONTHLY: 'Monthly',
    YEARLY: 'Yearly',
}

function humanizeSchedule(action: VisionActionApi): string {
    const rrule = action.trigger_config?.rrule
    if (!rrule) {
        return '—'
    }
    // Light-touch label for the common case; the full cadence editor lands with the create form (PR6).
    const freq = /FREQ=([A-Z]+)/.exec(rrule)?.[1]
    return (freq && FREQ_LABELS[freq]) || rrule
}

function deliverySummary(action: VisionActionApi): string {
    const targets = action.delivery_config ?? []
    return targets.length ? targets.map((t) => t.channel).join(', ') : '—'
}

export function VisionActionsTab({ scannerId }: { scannerId: string }): JSX.Element {
    return (
        <BindLogic logic={visionActionsLogic} props={{ scannerId }}>
            <VisionActionsTable />
        </BindLogic>
    )
}

function VisionActionsTable(): JSX.Element {
    const { visionActions, visionActionsLoading, togglingIds } = useValues(visionActionsLogic)
    const { toggleActionEnabled, deleteAction } = useActions(visionActionsLogic)

    if (!visionActionsLoading && visionActions.length === 0) {
        return (
            <ProductIntroduction
                productName="Scheduled summaries"
                thingName="action"
                isEmpty
                customHog={XRayHog}
                description="Set up scheduled summaries of this scanner's observations — synthesized by AI and delivered to Slack on the cadence you choose. Great for a daily digest of what the scanner has been finding."
                actionElementOverride={
                    <LemonButton
                        type="primary"
                        icon={<IconPlus />}
                        disabledReason="Action creation is coming soon"
                        data-attr="vision-action-new-empty"
                    >
                        New action
                    </LemonButton>
                }
            />
        )
    }

    const columns: LemonTableColumns<VisionActionApi> = [
        {
            title: 'Name',
            key: 'name',
            render: (_, action) => <span className="font-semibold">{action.name}</span>,
        },
        {
            title: 'Schedule',
            key: 'schedule',
            render: (_, action) => <span className="text-sm text-muted">{humanizeSchedule(action)}</span>,
        },
        {
            title: 'Delivery',
            key: 'delivery',
            render: (_, action) => <span className="text-sm">{deliverySummary(action)}</span>,
        },
        {
            title: 'Status',
            key: 'enabled',
            render: (_, action) => (
                <div className="flex items-center gap-2">
                    <AccessControlAction
                        resourceType={AccessControlResourceType.SessionRecording}
                        minAccessLevel={AccessControlLevel.Editor}
                    >
                        <LemonSwitch
                            checked={!!action.enabled}
                            onChange={() => toggleActionEnabled(action.id)}
                            disabled={togglingIds.includes(action.id)}
                            size="small"
                            data-attr="vision-action-toggle-enabled"
                        />
                    </AccessControlAction>
                    <span className={`inline-block min-w-[4.5rem] ${action.enabled ? 'text-success' : 'text-muted'}`}>
                        {action.enabled ? 'Enabled' : 'Disabled'}
                    </span>
                </div>
            ),
        },
        {
            title: 'Created by',
            key: 'created_by',
            render: (_, action) =>
                action.created_by ? (
                    <ProfilePicture
                        user={{
                            email: action.created_by.email,
                            first_name: action.created_by.first_name,
                            last_name: action.created_by.last_name,
                        }}
                        size="md"
                        showName
                    />
                ) : (
                    <span className="text-muted">—</span>
                ),
        },
        {
            title: '',
            key: 'actions',
            render: (_, action) => (
                <AccessControlAction
                    resourceType={AccessControlResourceType.SessionRecording}
                    minAccessLevel={AccessControlLevel.Editor}
                >
                    <LemonButton
                        size="small"
                        type="secondary"
                        status="danger"
                        icon={<IconTrash />}
                        tooltip="Delete"
                        data-attr="vision-action-delete"
                        onClick={() =>
                            LemonDialog.open({
                                title: `Delete "${action.name}"?`,
                                description:
                                    'This stops its scheduled summaries and removes its delivery destinations. This cannot be undone.',
                                primaryButton: {
                                    children: 'Delete',
                                    status: 'danger',
                                    onClick: () => deleteAction(action.id),
                                },
                                secondaryButton: { children: 'Cancel' },
                            })
                        }
                    />
                </AccessControlAction>
            ),
        },
    ]

    return (
        <LemonTable
            columns={columns}
            dataSource={visionActions}
            loading={visionActionsLoading}
            rowKey="id"
            data-attr="vision-actions-table"
            emptyState="No actions yet — this scanner has no scheduled summaries."
        />
    )
}
