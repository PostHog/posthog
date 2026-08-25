import { useActions, useValues } from 'kea'

import * as magnifyingGlassPng from '@posthog/brand/hoggies/png/magnifying-glass-1'
import { IconBell, IconEllipsis, IconPlus } from '@posthog/icons'
import {
    LemonButton,
    LemonDialog,
    LemonSwitch,
    LemonTable,
    LemonTableColumn,
    LemonTableColumns,
    LemonTag,
} from '@posthog/lemon-ui'

import { pngHoggie } from 'lib/brand/hoggies'
import { MemberSelect } from 'lib/components/MemberSelect'
import { ProductIntroduction } from 'lib/components/ProductIntroduction/ProductIntroduction'
import { TZLabel } from 'lib/components/TZLabel'
import type { LemonMenuItems } from 'lib/lemon-ui/LemonMenu'
import { LemonMenu } from 'lib/lemon-ui/LemonMenu'
import { createdByColumn } from 'lib/lemon-ui/LemonTable/columnUtils'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { urls } from 'scenes/urls'

import { ProductKey } from '~/queries/schema/schema-general'

import IconMicrosoftTeams from 'public/services/microsoft-teams.png'
import IconSlack from 'public/services/slack.png'
import IconWebhook from 'public/services/webhook.svg'

import {
    NotificationDestinationTypeEnumApi,
    LogsAlertConfigurationApi,
    LogsAlertConfigurationStateEnumApi,
    LogsAlertThresholdOperatorEnumApi,
} from 'products/logs/frontend/generated/api.schemas'

import { logsAlertingLogic } from './logsAlertingLogic'
import { LogsAlertStateIndicator } from './LogsAlertStateIndicator'
import { LogsAlertStateTimeline } from './LogsAlertStateTimeline'
import { SNOOZE_DURATIONS } from './logsAlertUtils'

const DESTINATION_TAGS = [
    { type: NotificationDestinationTypeEnumApi.Slack, label: 'Slack', icon: IconSlack },
    { type: NotificationDestinationTypeEnumApi.Webhook, label: 'Webhook', icon: IconWebhook },
    { type: NotificationDestinationTypeEnumApi.Teams, label: 'Teams', icon: IconMicrosoftTeams },
] as const

const HedgehogMagnifyingGlass = pngHoggie(magnifyingGlassPng)

function formatThreshold(alert: LogsAlertConfigurationApi): string {
    const operator = alert.threshold_operator === LogsAlertThresholdOperatorEnumApi.Below ? '<' : '>'
    return `${operator} ${alert.threshold_count} in ${alert.window_minutes}m`
}

export function LogsAlertDestinationTags({
    types,
}: {
    types: readonly NotificationDestinationTypeEnumApi[]
}): JSX.Element {
    return (
        <div className="flex gap-1">
            {DESTINATION_TAGS.filter(({ type }) => types.includes(type)).map(({ type, label, icon }) => (
                <LemonTag key={type}>
                    <img src={icon} alt="" className="h-3 w-3 object-contain" />
                    {label}
                </LemonTag>
            ))}
        </div>
    )
}

export function LogsAlertList(): JSX.Element {
    const { alerts, alertsLoading, resettingAlertIds, snoozingAlertIds, createdByFilter } = useValues(logsAlertingLogic)
    const {
        setCreatedByFilter,
        deleteAlert,
        toggleAlertEnabled,
        resetAlert,
        snoozeAlert,
        unsnoozeAlert,
        openCreateAlertModal,
        openEditAlertModal,
    } = useActions(logsAlertingLogic)

    const columns: LemonTableColumns<LogsAlertConfigurationApi> = [
        {
            title: 'Name',
            dataIndex: 'name',
            render: (_, alert) => (
                <LemonButton type="tertiary" size="small" onClick={() => openEditAlertModal(alert)}>
                    {alert.name}
                </LemonButton>
            ),
        },
        {
            title: 'Status',
            dataIndex: 'state',
            render: (_, alert) => (
                <LogsAlertStateIndicator
                    state={alert.state}
                    enabled={alert.enabled === true}
                    firstEnabledAt={alert.first_enabled_at}
                    lastErrorMessage={alert.last_error_message}
                    snoozeUntil={alert.snooze_until}
                />
            ),
        },
        {
            title: 'Threshold',
            render: (_, alert) => <span className="text-muted text-xs">{formatThreshold(alert)}</span>,
        },
        {
            title: 'Last checked',
            dataIndex: 'last_checked_at',
            render: (_, alert) =>
                alert.last_checked_at ? (
                    <TZLabel time={alert.last_checked_at} />
                ) : (
                    <span className="text-muted text-xs">Never</span>
                ),
        },
        {
            title: (
                <Tooltip title="When this alert is next scheduled to be evaluated. Alerts of the same cadence are spread across the cadence period to smooth load on the database.">
                    <span className="cursor-help">Next check</span>
                </Tooltip>
            ),
            dataIndex: 'next_check_at',
            render: (_, alert) =>
                alert.next_check_at ? (
                    <TZLabel time={alert.next_check_at} />
                ) : (
                    <span className="text-muted text-xs">Pending</span>
                ),
        },
        {
            title: (
                <Tooltip title="Alert state over the last 24 hours. Green = OK, red = firing, orange = resolving/errored, grey = snoozed or disabled. Hover to see the state at a point in time.">
                    <span className="cursor-help">Last 24h</span>
                </Tooltip>
            ),
            render: (_, alert) => <LogsAlertStateTimeline timeline={alert.state_timeline} className="h-6 w-72" />,
        },
        {
            title: 'Notifications',
            dataIndex: 'destination_types',
            render: (_, alert) => {
                const types = alert.destination_types ?? []
                const notifUrl = urls.logsAlertDetail(alert.id, 'notifications')
                if (types.length === 0) {
                    return (
                        <div className="flex items-center gap-1">
                            <LemonTag type="warning">None</LemonTag>
                            <LemonButton
                                size="small"
                                type="tertiary"
                                icon={
                                    <span className="relative inline-flex text-danger">
                                        <IconBell />
                                        <span aria-hidden className="absolute inset-0 flex items-center justify-center">
                                            <span className="block h-px w-[140%] rotate-45 bg-danger" />
                                        </span>
                                    </span>
                                }
                                to={notifUrl}
                                tooltip="No notification destinations configured — click to configure"
                            />
                        </div>
                    )
                }
                return (
                    <div className="flex items-center gap-1">
                        <LogsAlertDestinationTags types={types} />
                        <LemonButton
                            size="small"
                            type="tertiary"
                            icon={<IconBell />}
                            to={notifUrl}
                            tooltip="Configure notifications"
                        />
                    </div>
                )
            },
        },
        createdByColumn() as unknown as LemonTableColumn<
            LogsAlertConfigurationApi,
            keyof LogsAlertConfigurationApi | undefined
        >,
        {
            title: 'Enabled',
            dataIndex: 'enabled',
            render: (_, alert) => (
                <LemonSwitch
                    checked={alert.enabled === true}
                    onChange={() => toggleAlertEnabled(alert)}
                    disabledReason={
                        alert.state === LogsAlertConfigurationStateEnumApi.Broken
                            ? 'Reset this alert to re-enable checks'
                            : undefined
                    }
                    data-attr="logs-alert-row-toggle"
                />
            ),
        },
        {
            title: '',
            render: (_, alert) => {
                const isResetting = resettingAlertIds.has(alert.id)
                const isSnoozing = snoozingAlertIds.has(alert.id)
                let snoozeMenuItem: LemonMenuItems[number] | false = false
                if (alert.enabled === true && alert.state === LogsAlertConfigurationStateEnumApi.Snoozed) {
                    snoozeMenuItem = {
                        label: isSnoozing ? 'Unsnoozing…' : 'Unsnooze',
                        disabledReason: isSnoozing ? 'Updating snooze' : undefined,
                        onClick: () => unsnoozeAlert(alert.id),
                    }
                } else if (alert.enabled === true) {
                    snoozeMenuItem = {
                        label: isSnoozing ? 'Snoozing…' : 'Snooze',
                        disabledReason: isSnoozing ? 'Updating snooze' : undefined,
                        items: SNOOZE_DURATIONS.map((duration) => ({
                            label: duration.label,
                            onClick: () => snoozeAlert(alert.id, duration.minutes),
                        })),
                    }
                }
                const menuItems: LemonMenuItems = [
                    { label: 'Edit', onClick: () => openEditAlertModal(alert) },
                    { label: 'View history', to: urls.logsAlertDetail(alert.id, 'history') },
                    snoozeMenuItem,
                    alert.state === LogsAlertConfigurationStateEnumApi.Broken && {
                        label: isResetting ? 'Resetting…' : 'Reset alert',
                        disabledReason: isResetting ? 'Reset in progress' : undefined,
                        onClick: () => resetAlert(alert.id),
                    },
                    {
                        label: 'Delete',
                        status: 'danger',
                        'data-attr': 'logs-alert-row-delete',
                        onClick: () => {
                            LemonDialog.open({
                                title: `Delete "${alert.name}"?`,
                                description: 'This alert will be permanently deleted. This action cannot be undone.',
                                primaryButton: {
                                    children: 'Delete',
                                    type: 'primary',
                                    status: 'danger',
                                    onClick: () => deleteAlert(alert.id),
                                    'data-attr': 'logs-alert-delete-confirm',
                                },
                                secondaryButton: { children: 'Cancel' },
                            })
                        },
                    },
                ]

                return (
                    <LemonMenu items={menuItems} placement="bottom-end">
                        <LemonButton
                            type="tertiary"
                            size="small"
                            icon={<IconEllipsis />}
                            aria-label={`More options for ${alert.name}`}
                        />
                    </LemonMenu>
                )
            },
        },
    ]

    if (alerts.length === 0 && !createdByFilter && !alertsLoading) {
        return (
            <ProductIntroduction
                productName="Logs alerts"
                productKey={ProductKey.ALERTS}
                thingName="logs alert"
                description="Logs alerts notify you when matching logs cross a threshold."
                isEmpty
                customHog={HedgehogMagnifyingGlass}
                actionElementOverride={
                    <LemonButton
                        type="primary"
                        icon={<IconPlus />}
                        onClick={openCreateAlertModal}
                        data-attr="logs-alerts-new"
                    >
                        Create alert
                    </LemonButton>
                }
                docsURL="https://posthog.com/docs/logs/alerts"
            />
        )
    }

    return (
        <div className="space-y-2">
            <div className="flex justify-end gap-2 flex-wrap">
                <div className="flex items-center gap-2">
                    <span>Created by:</span>
                    <MemberSelect value={createdByFilter} onChange={(user) => setCreatedByFilter(user?.uuid ?? null)} />
                </div>
                <LemonButton type="primary" size="small" onClick={openCreateAlertModal} data-attr="logs-alerts-new">
                    New alert
                </LemonButton>
            </div>
            <LemonTable
                columns={columns}
                dataSource={alerts}
                rowKey="id"
                loading={alertsLoading}
                loadingSkeletonRows={5}
                emptyState={createdByFilter ? 'No alerts match this filter.' : 'No alerts configured yet.'}
                size="small"
                pagination={{ pageSize: 30 }}
                nouns={['alert', 'alerts']}
            />
        </div>
    )
}
