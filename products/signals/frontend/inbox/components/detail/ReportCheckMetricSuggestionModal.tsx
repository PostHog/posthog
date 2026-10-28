import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { LemonButton, LemonModal, LemonTextArea } from '@posthog/lemon-ui'

import { inboxTaskKickoffLogic } from '../../inboxTaskKickoffLogic'
import { SignalReport } from '../../types'

export function ReportCheckMetricSuggestionModal({
    report,
    reportUrl,
    isOpen,
    onClose,
}: {
    report: SignalReport
    reportUrl: string
    isOpen: boolean
    onClose: () => void
}): JSX.Element {
    const [description, setDescription] = useState('')
    const { openReportDiscussion, discussReport } = useActions(inboxTaskKickoffLogic)
    const { aiConsentDisabledReason, metricCheckReplacementDisabledReason, isDiscussing, isCreatingPr } =
        useValues(inboxTaskKickoffLogic)

    const submit = (): void => {
        const request = description.trim()
        if (
            !request ||
            isDiscussing ||
            isCreatingPr ||
            aiConsentDisabledReason ||
            metricCheckReplacementDisabledReason
        ) {
            return
        }
        openReportDiscussion(report, reportUrl)
        discussReport(report, reportUrl, request, undefined, 'check_metrics')
        onClose()
    }

    return (
        <LemonModal
            isOpen={isOpen}
            onClose={onClose}
            title="Describe what success would look like"
            width={560}
            footer={
                <>
                    <LemonButton type="secondary" onClick={onClose}>
                        Cancel
                    </LemonButton>
                    <LemonButton
                        data-attr="report-expected-impact-submit-suggestion"
                        type="primary"
                        onClick={submit}
                        loading={isDiscussing}
                        disabledReason={
                            aiConsentDisabledReason ??
                            metricCheckReplacementDisabledReason ??
                            (isCreatingPr ? 'An implementation is starting.' : undefined) ??
                            (!description.trim() ? 'Describe the outcome first.' : undefined)
                        }
                    >
                        Ask AI to update checks
                    </LemonButton>
                </>
            }
        >
            <LemonTextArea
                value={description}
                onChange={setDescription}
                placeholder="For example, fewer users should see the not-found page within a week."
                rows={4}
                maxLength={2000}
                data-attr="report-expected-impact-description"
            />
        </LemonModal>
    )
}
