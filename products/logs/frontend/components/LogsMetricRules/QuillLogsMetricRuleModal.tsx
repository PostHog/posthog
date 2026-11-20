import { useActions, useValues } from 'kea'

import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@posthog/quill'

import { logsMetricRulesSectionLogic } from './logsMetricRulesSectionLogic'
import { QuillLogsMetricRuleForm } from './QuillLogsMetricRuleForm'

export function QuillLogsMetricRuleModal(): JSX.Element | null {
    const { ruleModalOpen, editingRule } = useValues(logsMetricRulesSectionLogic)
    const { closeRuleModal } = useActions(logsMetricRulesSectionLogic)

    if (!ruleModalOpen) {
        return null
    }

    return (
        <Dialog
            open
            onOpenChange={(open: boolean) => {
                if (!open) {
                    closeRuleModal()
                }
            }}
        >
            <DialogContent className="sm:max-w-180">
                <DialogHeader>
                    <DialogTitle>{editingRule ? 'Edit log-based metric' : 'New log-based metric'}</DialogTitle>
                </DialogHeader>
                <QuillLogsMetricRuleForm rule={editingRule} onCancel={closeRuleModal} />
            </DialogContent>
        </Dialog>
    )
}
