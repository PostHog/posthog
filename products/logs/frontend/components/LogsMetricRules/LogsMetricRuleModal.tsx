import { useActions, useValues } from 'kea'

import { LemonModal } from '@posthog/lemon-ui'

import { LogsMetricRuleForm } from './LogsMetricRuleForm'
import { logsMetricRulesSectionLogic } from './logsMetricRulesSectionLogic'

/** The create/edit modal used by the settings section's rule table. */
export function LogsMetricRuleModal(): JSX.Element | null {
    const { ruleModalOpen, editingRule } = useValues(logsMetricRulesSectionLogic)
    const { closeRuleModal } = useActions(logsMetricRulesSectionLogic)

    if (!ruleModalOpen) {
        return null
    }
    return (
        <LemonModal
            isOpen
            onClose={closeRuleModal}
            title={editingRule ? 'Edit log-based metric' : 'New log-based metric'}
            width={720}
            footer={null}
        >
            <LogsMetricRuleForm rule={editingRule} onCancel={closeRuleModal} />
        </LemonModal>
    )
}
