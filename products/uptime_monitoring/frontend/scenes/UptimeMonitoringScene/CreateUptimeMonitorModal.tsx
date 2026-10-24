import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import { LemonButton, LemonInput, LemonModal, LemonSelect } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'

import { formatInterval, uptimeMonitoringSceneLogic } from './uptimeMonitoringSceneLogic'

const INTERVAL_OPTIONS = [60, 300, 900, 3600].map((seconds) => ({ value: seconds, label: formatInterval(seconds) }))

export function CreateUptimeMonitorModal(): JSX.Element {
    const { isCreateModalOpen, isNewMonitorSubmitting } = useValues(uptimeMonitoringSceneLogic)
    const { closeCreateModal } = useActions(uptimeMonitoringSceneLogic)

    return (
        <LemonModal isOpen={isCreateModalOpen} onClose={isNewMonitorSubmitting ? undefined : closeCreateModal} simple>
            <Form
                logic={uptimeMonitoringSceneLogic}
                formKey="newMonitor"
                enableFormOnSubmit
                className="LemonModal__layout"
            >
                <LemonModal.Header>
                    <h3>New monitor</h3>
                </LemonModal.Header>
                <LemonModal.Content className="space-y-4">
                    <LemonField name="name" label="Name">
                        <LemonInput placeholder="Marketing site" data-attr="uptime-monitoring-create-name" />
                    </LemonField>
                    <LemonField name="url" label="URL">
                        <LemonInput placeholder="https://example.com" data-attr="uptime-monitoring-create-url" />
                    </LemonField>
                    <LemonField name="interval_seconds" label="Check interval">
                        <LemonSelect options={INTERVAL_OPTIONS} data-attr="uptime-monitoring-create-interval" />
                    </LemonField>
                </LemonModal.Content>
                <LemonModal.Footer>
                    <LemonButton
                        type="secondary"
                        onClick={closeCreateModal}
                        disabledReason={isNewMonitorSubmitting ? 'Creating the monitor' : undefined}
                        data-attr="uptime-monitoring-create-cancel"
                    >
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        htmlType="submit"
                        loading={isNewMonitorSubmitting}
                        data-attr="uptime-monitoring-create-submit"
                    >
                        Create monitor
                    </LemonButton>
                </LemonModal.Footer>
            </Form>
        </LemonModal>
    )
}
