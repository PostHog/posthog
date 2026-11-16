import { BindLogic, useActions, useValues } from 'kea'

import { LemonBanner } from '@posthog/lemon-ui'

import { TRACING_SCENE_VIEWER_ID, tracingFiltersLogic } from '../tracingFiltersLogic'
import { TracesAlertCreateModal } from './TracesAlertCreateModal'
import { TracesAlertEditModal } from './TracesAlertEditModal'
import { TracesAlertHistoryModal } from './TracesAlertHistoryModal'
import { TracesAlertList } from './TracesAlertList'
import { tracesAlertsLogic } from './tracesAlertsLogic'

export function TracesAlertsTab(): JSX.Element {
    return (
        <BindLogic logic={tracesAlertsLogic} props={{}}>
            <TracesAlertsTabContent />
        </BindLogic>
    )
}

function TracesAlertsTabContent(): JSX.Element {
    const { isCreateAlertModalOpen, editingAlert, historyAlert } = useValues(tracesAlertsLogic)
    const { closeCreateAlertModal, closeEditAlertModal, closeHistoryModal } = useActions(tracesAlertsLogic)
    const { filters } = useValues(tracingFiltersLogic({ id: TRACING_SCENE_VIEWER_ID }))

    return (
        <div className="flex flex-col gap-y-3">
            <LemonBanner type="info" dismissKey="traces-alerts-beta-banner">
                Traces alerting is in beta. Each alert checks request counts, errors or latency every minute. A new
                alert starts from the services and filters the viewer is showing.
            </LemonBanner>
            <TracesAlertList />
            <TracesAlertCreateModal
                isOpen={isCreateAlertModalOpen}
                onClose={closeCreateAlertModal}
                viewerFilters={{ serviceNames: filters.serviceNames, filterGroup: filters.filterGroup }}
            />
            <TracesAlertEditModal alert={editingAlert} onClose={closeEditAlertModal} />
            <TracesAlertHistoryModal alert={historyAlert} onClose={closeHistoryModal} />
        </div>
    )
}
