import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import { LemonButton, LemonInput, LemonModal, LemonSelect } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'

import { uptimeMonitoringSceneLogic } from './uptimeMonitoringSceneLogic'

const INTERVAL_OPTIONS = [
    { value: 60, label: 'Every minute' },
    { value: 300, label: 'Every 5 minutes' },
    { value: 900, label: 'Every 15 minutes' },
    { value: 3600, label: 'Every hour' },
]

export function CreateUptimeMonitorModal(): JSX.Element {
    const { isCreateModalOpen, isNewMonitorSubmitting } = useValues(uptimeMonitoringSceneLogic)
    const { closeCreateModal, submitNewMonitor } = useActions(uptimeMonitoringSceneLogic)

    return (
        <LemonModal
            isOpen={isCreateModalOpen}
            onClose={closeCreateModal}
            title="New monitor"
            footer={
                <>
                    <LemonButton
                        type="secondary"
                        onClick={closeCreateModal}
                        data-attr="uptime-monitoring-create-cancel"
                    >
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        onClick={submitNewMonitor}
                        loading={isNewMonitorSubmitting}
                        data-attr="uptime-monitoring-create-submit"
                    >
                        Create monitor
                    </LemonButton>
                </>
            }
        >
            <Form logic={uptimeMonitoringSceneLogic} formKey="newMonitor" enableFormOnSubmit className="space-y-4">
                <LemonField name="name" label="Name">
                    <LemonInput placeholder="Marketing site" data-attr="uptime-monitoring-create-name" />
                </LemonField>
                <LemonField name="url" label="URL">
                    <LemonInput placeholder="https://example.com" data-attr="uptime-monitoring-create-url" />
                </LemonField>
                <LemonField name="interval_seconds" label="Check interval">
                    <LemonSelect options={INTERVAL_OPTIONS} data-attr="uptime-monitoring-create-interval" />
                </LemonField>
            </Form>
        </LemonModal>
    )
}
