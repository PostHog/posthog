import { BindLogic, useActions, useValues } from 'kea'

import { IconPlus, IconRefresh } from '@posthog/icons'
import { LemonButton, LemonSwitch, LemonTable, LemonTag, Link } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture'

import type { VisionAlertConfigurationApi } from '../../generated/api.schemas'
import { getReplayVisionEditDisabledReason } from '../../utils/accessControl'
import { replayScannerLogic } from '../replayScannerLogic'
import { scannerAlertsLogic } from '../scannerAlertsLogic'
import { conditionSummary, selectionSummary } from '../scannerAlertUtils'
import { ScannerAlertCreateModal } from './ScannerAlertCreateModal'
import { ScannerAlertEditModal } from './ScannerAlertEditModal'
import { ScannerAlertStateTag } from './ScannerAlertStateTag'

export function ScannerAlertsTab({ scannerId }: { scannerId: string }): JSX.Element {
    return (
        <BindLogic logic={scannerAlertsLogic} props={{ scannerId }}>
            <ScannerAlertsTabContent scannerId={scannerId} />
        </BindLogic>
    )
}

function ScannerAlertsTabContent({ scannerId }: { scannerId: string }): JSX.Element {
    const { alerts, alertsLoading, busyAlertIds, isCreateAlertModalOpen, editingAlert } = useValues(scannerAlertsLogic)
    const {
        toggleAlertEnabled,
        resetAlert,
        openCreateAlertModal,
        closeCreateAlertModal,
        openEditAlertModal,
        closeEditAlertModal,
    } = useActions(scannerAlertsLogic)
    const { scanner } = useValues(replayScannerLogic({ id: scannerId }))
    const scannerType = scanner?.scanner_type
    const editDisabledReason = getReplayVisionEditDisabledReason(scanner?.user_access_level)

    const columns: LemonTableColumns<VisionAlertConfigurationApi> = [
        {
            title: 'Name',
            key: 'name',
            render: (_, alert) => (
                <span className="flex items-center gap-2">
                    <Link
                        className="font-semibold"
                        onClick={() => openEditAlertModal(alert)}
                        data-attr="vision-alert-open-edit"
                    >
                        {alert.name}
                    </Link>
                    <LemonTag type="default">{alert.kind === 'match' ? 'Every match' : 'Metric threshold'}</LemonTag>
                </span>
            ),
        },
        {
            title: 'Condition',
            key: 'condition',
            render: (_, alert) => (
                <div className="text-sm">
                    <div>{conditionSummary(alert)}</div>
                    <div className="text-muted text-xs">{selectionSummary(alert)}</div>
                </div>
            ),
        },
        {
            title: 'Status',
            key: 'status',
            render: (_, alert) => (
                <div className="flex items-center gap-2">
                    <ScannerAlertStateTag alert={alert} />
                    {alert.state === 'broken' ? (
                        <LemonButton
                            size="xsmall"
                            type="secondary"
                            icon={<IconRefresh />}
                            tooltip="Reset the alert and run a check shortly"
                            onClick={() => resetAlert(alert.id)}
                            loading={busyAlertIds.has(alert.id)}
                            disabledReason={editDisabledReason}
                            data-attr="vision-alert-reset"
                        >
                            Reset
                        </LemonButton>
                    ) : null}
                </div>
            ),
        },
        {
            title: 'Last checked',
            key: 'last_checked',
            render: (_, alert) =>
                alert.kind === 'match' ? (
                    <span className="text-muted text-sm">Continuous</span>
                ) : alert.last_checked_at ? (
                    <TZLabel time={alert.last_checked_at} formatDate="MMM D" formatTime="HH:mm" />
                ) : (
                    <span className="text-muted">Not yet</span>
                ),
        },
        {
            title: 'Created by',
            key: 'created_by',
            render: (_, alert) =>
                alert.created_by ? (
                    <ProfilePicture
                        user={{
                            email: alert.created_by.email,
                            first_name: alert.created_by.first_name,
                            last_name: alert.created_by.last_name,
                        }}
                        size="md"
                        showName
                    />
                ) : (
                    <span className="text-muted">—</span>
                ),
        },
        {
            title: 'Enabled',
            key: 'enabled',
            width: 0,
            render: (_, alert) => (
                <LemonSwitch
                    checked={alert.enabled ?? true}
                    onChange={() => toggleAlertEnabled(alert)}
                    disabled={busyAlertIds.has(alert.id)}
                    disabledReason={editDisabledReason}
                    size="small"
                    data-attr="vision-alert-toggle-enabled"
                />
            ),
        },
    ]

    return (
        <div className="flex flex-col gap-2">
            <LemonTable
                columns={columns}
                dataSource={alerts}
                loading={alertsLoading}
                rowKey="id"
                data-attr="vision-alerts-table"
                emptyState="No alerts on this scanner yet. Create one to get notified about matching observations or metric thresholds."
            />
            <div className="flex justify-center">
                <LemonButton
                    type="primary"
                    icon={<IconPlus />}
                    onClick={openCreateAlertModal}
                    disabledReason={editDisabledReason}
                    data-attr="vision-alert-new"
                >
                    New alert
                </LemonButton>
            </div>
            <ScannerAlertCreateModal
                scannerId={scannerId}
                scannerType={scannerType}
                isOpen={isCreateAlertModalOpen}
                onClose={closeCreateAlertModal}
            />
            <ScannerAlertEditModal
                scannerId={scannerId}
                scannerType={scannerType}
                alert={editingAlert}
                onClose={closeEditAlertModal}
            />
        </div>
    )
}
