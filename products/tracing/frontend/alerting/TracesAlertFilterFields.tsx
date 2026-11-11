import { useActions, useValues } from 'kea'

import { LemonInput } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'

import { TracingServiceFilter } from '../components/TracingServiceFilter'
import { TracesAlertAttributeFilters } from './TracesAlertAttributeFilters'
import { tracesAlertFormLogic } from './tracesAlertFormLogic'
import { SUGGESTION_RANGE } from './tracesAlertUtils'

export function TracesAlertFilterFields({ nameError }: { nameError?: string }): JSX.Element {
    const { alertForm } = useValues(tracesAlertFormLogic)
    const { setAlertFormValue } = useActions(tracesAlertFormLogic)

    return (
        <div className="space-y-4">
            <LemonField.Pure label="Name" error={nameError}>
                <LemonInput
                    value={alertForm.name}
                    onChange={(name) => setAlertFormValue('name', name)}
                    placeholder="For example checkout errors"
                    data-attr="traces-alert-name"
                />
            </LemonField.Pure>
            <div className="space-y-2">
                <h4 className="m-0">Requests to measure</h4>
                <p className="text-sm text-secondary m-0">
                    A request is a trace's root span, or a server or consumer span.
                </p>
                <div className="flex flex-wrap items-start gap-2">
                    <TracingServiceFilter
                        value={alertForm.serviceNames}
                        onChange={(serviceNames) => setAlertFormValue('serviceNames', serviceNames)}
                        dateRange={SUGGESTION_RANGE}
                    />
                    <TracesAlertAttributeFilters
                        filterGroup={alertForm.filterGroup}
                        serviceNames={alertForm.serviceNames}
                        onChange={(filterGroup) => setAlertFormValue('filterGroup', filterGroup)}
                    />
                </div>
            </div>
        </div>
    )
}
