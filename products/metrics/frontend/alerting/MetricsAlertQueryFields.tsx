import { useActions, useValues } from 'kea'

import { LemonTextArea } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'

import { AlertEditorFormDetails } from 'products/alerts/frontend/components/AlertEditor'

import { metricsAlertFormLogic } from './metricsAlertFormLogic'

export function MetricsAlertQueryFields({
    nameError,
    queryError,
}: {
    nameError?: string
    queryError?: string
}): JSX.Element {
    const { alertForm } = useValues(metricsAlertFormLogic)
    const { setAlertFormValue } = useActions(metricsAlertFormLogic)
    return (
        <div className="space-y-4">
            <AlertEditorFormDetails nameError={nameError} nameDataAttr="metrics-alert-name" />
            {/* Pure, so the wizard decides when the error shows. */}
            <LemonField.Pure
                label="PromQL query"
                help="Each series the query returns is checked on its own. For a threshold, leave the comparison out of the query."
                error={queryError}
            >
                <LemonTextArea
                    className="font-mono"
                    placeholder="sum by (service_name) (rate(http_requests_errors_total[5m]))"
                    minRows={3}
                    value={alertForm.query}
                    onChange={(query) => setAlertFormValue('query', query)}
                    data-attr="metrics-alert-query"
                />
            </LemonField.Pure>
        </div>
    )
}
