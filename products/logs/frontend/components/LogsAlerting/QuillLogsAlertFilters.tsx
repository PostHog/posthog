import { useActions, useValues } from 'kea'
import { useCallback } from 'react'

import { Field, FieldError, FieldTitle, Heading } from '@posthog/quill'

import { UniversalFiltersGroup } from '~/types'

import { ServiceFilter } from 'products/logs/frontend/components/LogsViewer/Filters/ServiceFilter'
import { SeverityLevelsFilter } from 'products/logs/frontend/components/LogsViewer/Filters/SeverityLevelsFilter'

import { AlertFilterGroup } from './LogsAlertFilterGroup'
import { logsAlertFormLogic } from './logsAlertFormLogic'

export function QuillLogsAlertFilters({ filterError }: { filterError?: string }): JSX.Element {
    const { alertForm, alertFormValidationErrors } = useValues(logsAlertFormLogic)
    const { setAlertFormValue } = useActions(logsAlertFormLogic)
    const handleFilterGroupChange = useCallback(
        (group: UniversalFiltersGroup) => setAlertFormValue('filterGroup', group),
        [setAlertFormValue]
    )
    const severityError = alertFormValidationErrors.severityLevels as string | undefined

    return (
        <div className="@container flex flex-col gap-3">
            <Heading size="sm" render={<h4 className="m-0" />}>
                Filters
            </Heading>
            {filterError ? <FieldError>{filterError}</FieldError> : null}
            <div className="grid gap-3 @lg:grid-cols-2">
                <Field data-invalid={severityError ? true : undefined}>
                    <FieldTitle>Severity</FieldTitle>
                    <SeverityLevelsFilter
                        value={alertForm.severityLevels}
                        onChange={(levels) => setAlertFormValue('severityLevels', levels)}
                        showBulkActions
                    />
                    {severityError ? <FieldError>{severityError}</FieldError> : null}
                </Field>
                <Field>
                    <FieldTitle>Service</FieldTitle>
                    <ServiceFilter
                        value={alertForm.serviceNames}
                        onChange={(names) => setAlertFormValue('serviceNames', names)}
                    />
                </Field>
            </div>
            <Field>
                <FieldTitle>Attributes</FieldTitle>
                <AlertFilterGroup filterGroup={alertForm.filterGroup} onChange={handleFilterGroupChange} />
            </Field>
        </div>
    )
}
