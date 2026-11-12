import { useActions, useValues } from 'kea'

import { TracingServiceFilter } from '../components/TracingServiceFilter'
import { TracesAlertAttributeFilters } from './TracesAlertAttributeFilters'
import { tracesAlertFormLogic } from './tracesAlertFormLogic'
import { SUGGESTION_RANGE } from './tracesAlertUtils'

export function TracesAlertFilterFields(): JSX.Element {
    const { alertForm } = useValues(tracesAlertFormLogic)
    const { setAlertFormValue } = useActions(tracesAlertFormLogic)

    return (
        <div className="space-y-4">
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
