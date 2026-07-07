import { BindLogic, useActions, useValues } from 'kea'

import { HedgehogXRay } from '@posthog/brand/hoggies'
import { IconPencil, IconPlus, IconTrash } from '@posthog/icons'
import { LemonButton, LemonSwitch, LemonTable, Link } from '@posthog/lemon-ui'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { ProductIntroduction } from 'lib/components/ProductIntroduction/ProductIntroduction'
import { slackChannelDisplayName } from 'lib/integrations/slackChannel'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture'
import { urls } from 'scenes/urls'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

import type { VisionActionApi } from '../../generated/api.schemas'
import { humanizeCadence, parseRruleToCadence } from '../cadence'
import { visionActionsLogic } from '../visionActionsLogic'

function humanizeSchedule(action: VisionActionApi): string {
    const rrule = action.trigger_config?.rrule
    if (!rrule) {
        return '—'
    }
    // parseRruleToCadence only understands DAILY/WEEKLY; for anything else (a legacy monthly/hourly
    // rrule) it falls back to the default daily cadence, which would mislabel the schedule — show the
    // raw rrule instead of a fabricated "Daily".
    const freq = /FREQ=([A-Z]+)/.exec(rrule)?.[1]
    if (freq !== 'DAILY' && freq !== 'WEEKLY') {
        return rrule
    }
    return humanizeCadence(parseRruleToCadence(rrule))
}

// Every write control on this tab gates on the same session-recording Editor access — wrap once.
function EditorGate({ children }: { children: JSX.Element }): JSX.Element {
    return (
        <AccessControlAction
            resourceType={AccessControlResourceType.SessionRecording}
            minAccessLevel={AccessControlLevel.Editor}
        >
            {children}
        </AccessControlAction>
    )
}

function deliverySummary(action: VisionActionApi): string {
    const targets = action.delivery_config ?? []
    if (!targets.length) {
        return '—'
    }
    return targets
        .map((t) => {
            // channel is the `${id}|#${name}` picker composite for actions saved with a friendly name;
            // fall back to "Slack" rather than exposing a bare channel id (older rows, id-only input).
            const name = slackChannelDisplayName(t.channel)
            return name.startsWith('#') ? name : 'Slack'
        })
        .join(', ')
}

export function VisionActionsTab({ scannerId }: { scannerId: string }): JSX.Element {
    return (
        <BindLogic logic={visionActionsLogic} props={{ scannerId }}>
            <VisionActionsTable scannerId={scannerId} />
        </BindLogic>
    )
}

function VisionActionsTable({ scannerId }: { scannerId: string }): JSX.Element {
    const { visionActions, visionActionsLoading, togglingIds } = useValues(visionActionsLogic)
    const { toggleActionEnabled, deleteAction } = useActions(visionActionsLogic)

    if (!visionActionsLoading && visionActions.length === 0) {
        return (
            <ProductIntroduction
                productName="Scheduled summaries"
                thingName="summary"
                isEmpty
                customHog={HedgehogXRay}
                description="Set up scheduled summaries of this scanner's observations — synthesized by AI and delivered to Slack on the cadence you choose. Great for a daily digest of what the scanner has been finding."
                actionElementOverride={
                    <EditorGate>
                        <LemonButton
                            type="primary"
                            icon={<IconPlus />}
                            to={urls.replayVisionActionNew(scannerId)}
                            data-attr="vision-action-new-empty"
                        >
                            New summary
                        </LemonButton>
                    </EditorGate>
                }
            />
        )
    }

    const columns: LemonTableColumns<VisionActionApi> = [
        {
            title: 'Name',
            key: 'name',
            render: (_, action) => (
                <Link
                    className="font-semibold"
                    to={urls.replayVisionAction(action.id)}
                    data-attr="vision-action-view-runs"
                >
                    {action.name}
                </Link>
            ),
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
                    <EditorGate>
                        <LemonSwitch
                            checked={!!action.enabled}
                            onChange={() => toggleActionEnabled(action.id)}
                            disabled={togglingIds.includes(action.id)}
                            size="small"
                            data-attr="vision-action-toggle-enabled"
                        />
                    </EditorGate>
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
                    <EditorGate>
                        <LemonButton
                            size="small"
                            type="secondary"
                            icon={<IconPencil />}
                            tooltip="Edit"
                            data-attr="vision-action-edit"
                            to={urls.replayVisionActionEdit(action.id)}
                        />
                    </EditorGate>
                    <EditorGate>
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
                    </EditorGate>
                </div>
            ),
        },
    ]

    return (
        <div className="flex flex-col gap-2">
            <div className="flex justify-end">
                <EditorGate>
                    <LemonButton
                        type="primary"
                        icon={<IconPlus />}
                        to={urls.replayVisionActionNew(scannerId)}
                        data-attr="vision-action-new"
                    >
                        New summary
                    </LemonButton>
                </EditorGate>
            </div>
            <LemonTable
                columns={columns}
                dataSource={visionActions}
                loading={visionActionsLoading}
                rowKey="id"
                data-attr="vision-actions-table"
                emptyState="No summaries scheduled for this scanner yet."
            />
        </div>
    )
}
