import { useActions, useValues } from 'kea'

import { LemonButton, LemonModal } from '@posthog/lemon-ui'

import { aiConsentLogic } from 'scenes/settings/organization/aiConsentLogic'
import { AIConsentPopoverWrapper } from 'scenes/settings/organization/AIConsentPopoverWrapper'

import type { DashboardImportSourceEnumApi } from 'products/metrics/frontend/generated/api.schemas'

import { metricsDashboardImportLogic } from './metricsDashboardImportLogic'
import { DashboardImportInput } from './steps/DashboardImportInput'
import { DashboardImportProgress } from './steps/DashboardImportProgress'
import { DashboardImportSummary } from './steps/DashboardImportSummary'

const TITLES: Record<DashboardImportSourceEnumApi, string> = {
    grafana: 'Import from Grafana',
    screenshot: 'Import from screenshot',
}

export function MetricsDashboardImportModal(): JSX.Element {
    const { isModalOpen, step, source, starting, importDisabledReason, currentImport } =
        useValues(metricsDashboardImportLogic)
    const { closeImportModal, startImport, resetImport, backToInput, openImportedDashboard } =
        useActions(metricsDashboardImportLogic)
    const { dataProcessingAccepted } = useValues(aiConsentLogic)

    const footer =
        step === 'input' ? (
            <>
                <LemonButton
                    type="secondary"
                    onClick={closeImportModal}
                    disabledReason={starting ? 'The import is starting' : undefined}
                >
                    Cancel
                </LemonButton>
                {/* Stays visible until the organization approves AI data processing, also after a dismissal. */}
                <AIConsentPopoverWrapper placement="bottom-end" showArrow hidden={!isModalOpen} ignoreDismissal>
                    <LemonButton
                        type="primary"
                        sideIcon={null}
                        onClick={startImport}
                        loading={starting}
                        disabledReason={
                            dataProcessingAccepted
                                ? importDisabledReason
                                : 'Your organization must approve AI data processing first'
                        }
                        data-attr="metrics-dashboard-import-start"
                    >
                        Import
                    </LemonButton>
                </AIConsentPopoverWrapper>
            </>
        ) : step === 'progress' ? (
            <LemonButton type="secondary" onClick={closeImportModal} data-attr="metrics-dashboard-import-hide">
                Close
            </LemonButton>
        ) : currentImport?.dashboard_id ? (
            <>
                <LemonButton type="secondary" onClick={resetImport} data-attr="metrics-dashboard-import-another">
                    Import another
                </LemonButton>
                <LemonButton type="primary" onClick={openImportedDashboard} data-attr="metrics-dashboard-import-open">
                    Open dashboard
                </LemonButton>
            </>
        ) : (
            <>
                <LemonButton type="secondary" onClick={closeImportModal}>
                    Close
                </LemonButton>
                <LemonButton type="primary" onClick={backToInput} data-attr="metrics-dashboard-import-retry">
                    Try again
                </LemonButton>
            </>
        )

    return (
        <LemonModal
            isOpen={isModalOpen}
            onClose={closeImportModal}
            closable={!starting}
            title={TITLES[currentImport?.source ?? source]}
            width={640}
            footer={footer}
        >
            {step === 'input' ? (
                <DashboardImportInput />
            ) : step === 'progress' ? (
                <DashboardImportProgress />
            ) : (
                <DashboardImportSummary />
            )}
        </LemonModal>
    )
}
