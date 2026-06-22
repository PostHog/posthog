import { BindLogic, useActions, useValues } from 'kea'

import { IconPencil, IconPlus, IconTrash } from '@posthog/icons'
import { LemonButton, LemonSwitch, LemonTable } from '@posthog/lemon-ui'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { XRayHog } from 'lib/components/hedgehogs'
import { ProductIntroduction } from 'lib/components/ProductIntroduction/ProductIntroduction'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

import type { VisionActionApi } from '../../generated/api.schemas'
import { humanizeCadence, parseRruleToCadence } from '../cadence'
import { visionActionsLogic } from '../visionActionsLogic'
import { VisionActionForm } from './VisionActionForm'

function humanizeSchedule(action: VisionActionApi): string {
    const rrule = action.trigger_config?.rrule
    return rrule ? humanizeCadence(parseRruleToCadence(rrule)) : '—'
}

function deliverySummary(action: VisionActionApi): string {
    const targets = action.delivery_config ?? []
    return targets.length ? targets.map((t) => t.channel).join(', ') : '—'
}

export function VisionActionsTab({ scannerId }: { scannerId: string }): JSX.Element {
    return (
        <BindLogic logic={visionActionsLogic} props={{ scannerId }}>
            <VisionActionsTable />
            <VisionActionForm scannerId={scannerId} />
        </BindLogic>
    )
}

function VisionActionsTable(): JSX.Element {
    const { visionActions, visionActionsLoading, togglingIds } = useValues(visionActionsLogic)
    const { toggleActionEnabled, deleteAction, openCreateForm, openEditForm } = useActions(visionActionsLogic)

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
                        onClick={() => openCreateForm()}
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
            title: 'Actions',
            key: 'actions',
            width: 0, // shrink to content so the buttons hug the right instead of floating in a wide column
            render: (_, action) => (
                <div className="flex gap-1">
                    <AccessControlAction
                        resourceType={AccessControlResourceType.SessionRecording}
                        minAccessLevel={AccessControlLevel.Editor}
                    >
                        <LemonButton
                            size="small"
                            type="secondary"
                            icon={<IconPencil />}
                            tooltip="Edit"
                            data-attr="vision-action-edit"
                            onClick={() => openEditForm(action)}
                        />
                    </AccessControlAction>
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
                </div>
            ),
        },
    ]

    return (
        <div className="flex flex-col gap-2">
            <div className="flex justify-end">
                <AccessControlAction
                    resourceType={AccessControlResourceType.SessionRecording}
                    minAccessLevel={AccessControlLevel.Editor}
                >
                    <LemonButton
                        type="primary"
                        icon={<IconPlus />}
                        onClick={() => openCreateForm()}
                        data-attr="vision-action-new"
                    >
                        New action
                    </LemonButton>
                </AccessControlAction>
            </div>
            <LemonTable
                columns={columns}
                dataSource={visionActions}
                loading={visionActionsLoading}
                rowKey="id"
                data-attr="vision-actions-table"
                emptyState="No actions yet — this scanner has no scheduled summaries."
            />
        </div>
    )
}
