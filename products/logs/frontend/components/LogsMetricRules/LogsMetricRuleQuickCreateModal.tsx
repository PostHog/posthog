import { useActions, useValues } from 'kea'

import { LemonModal } from '@posthog/lemon-ui'

import { LogsMetricRuleForm } from './LogsMetricRuleForm'
import { logsMetricRuleQuickCreateLogic } from './logsMetricRuleQuickCreateLogic'

/** The create-only modal launched from a log row in the viewer, prefilled from that log. */
export function LogsMetricRuleQuickCreateModal(): JSX.Element | null {
    const { seed } = useValues(logsMetricRuleQuickCreateLogic)
    const { closeQuickCreateModal } = useActions(logsMetricRuleQuickCreateLogic)

    if (!seed) {
        return null
    }
    return (
        <LemonModal isOpen onClose={closeQuickCreateModal} title="New log-based metric" width={720} footer={null}>
            <LogsMetricRuleForm rule={null} seed={seed} onCancel={closeQuickCreateModal} />
        </LemonModal>
    )
}
