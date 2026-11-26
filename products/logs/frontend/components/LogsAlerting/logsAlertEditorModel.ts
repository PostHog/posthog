import type { DeepPartialMap, ValidationErrorType } from 'kea-forms'

import type { WizardReviewItem } from 'lib/components/WizardReview'

import { AlertSummaryParts } from 'products/alerts/frontend/components/alertSummary'
import { AlertDestinationEntry } from 'products/alerts_platform/frontend/destinations/platformAlertDestinations'
import { PlatformAlertCreateDestinationApi } from 'products/alerts_platform/frontend/generated/api.schemas'

import { LogsAlertFormType } from './logsAlertFormLogic'
import { GROUP_BY_LABELS } from './logsAlertGrouping'
import { hasAnyFilter } from './logsAlertUtils'

export interface LogsAlertCreateValidation {
    nameError: string | undefined
    filterError: string | undefined
    configurationCannotAdvanceReason: string | undefined
    triggerCannotAdvanceReason: string | undefined
}

export function getLogsAlertCreateValidation(
    alertForm: LogsAlertFormType,
    alertFormValidationErrors: DeepPartialMap<LogsAlertFormType, ValidationErrorType>
): LogsAlertCreateValidation {
    const hasLogFilter = hasAnyFilter(alertForm.severityLevels, alertForm.serviceNames, alertForm.filterGroup)
    const nameError = alertForm.name.trim() ? undefined : 'Enter an alert name.'
    const filterError = hasLogFilter
        ? undefined
        : 'Select at least one severity or service, or add an attribute filter.'
    const configurationCannotAdvanceReason = nameError ?? filterError
    const triggerCannotAdvanceReason = alertFormValidationErrors.maxInstances as string | undefined

    return { nameError, filterError, configurationCannotAdvanceReason, triggerCannotAdvanceReason }
}

export function buildLogsAlertReviewItems(
    alertForm: LogsAlertFormType,
    pendingDestinations: PlatformAlertCreateDestinationApi[],
    canGroup: boolean
): WizardReviewItem[] {
    const severity = alertForm.severityLevels.length ? alertForm.severityLevels.join(', ') : 'all severities'
    const services = alertForm.serviceNames.length ? alertForm.serviceNames.join(', ') : 'all services'
    const attributeCount = alertForm.filterGroup.values.length
    const notificationSummary = pendingDestinations.length
        ? `${pendingDestinations.length} notification destination${pendingDestinations.length === 1 ? '' : 's'}`
        : 'No notification destinations'

    return [
        { label: 'Name', value: alertForm.name },
        { label: 'Severity', value: severity },
        { label: 'Service', value: services },
        {
            label: 'Attributes',
            value: attributeCount ? `${attributeCount} attribute filter${attributeCount === 1 ? '' : 's'}` : 'None',
        },
        {
            label: 'Fires when',
            value: `log count is ${alertForm.thresholdOperator} ${alertForm.thresholdCount} in ${alertForm.windowMinutes} minutes`,
        },
        ...(canGroup
            ? [
                  {
                      label: 'Group by',
                      value:
                          alertForm.groupBy === 'none'
                              ? GROUP_BY_LABELS.none
                              : `${GROUP_BY_LABELS[alertForm.groupBy]}, up to ${alertForm.maxInstances} groups`,
                  },
              ]
            : []),
        {
            label: 'Noise reduction',
            value: `${alertForm.datapointsToAlarm} of ${alertForm.evaluationPeriods} checks must match`,
        },
        { label: 'Notification cooldown', value: `${alertForm.cooldownMinutes} minutes` },
        { label: 'Notifies', value: notificationSummary },
    ]
}

export function buildLogsAlertEditSummary(
    alertForm: LogsAlertFormType,
    destinations: AlertDestinationEntry[]
): AlertSummaryParts {
    const filterParts: string[] = []
    if (alertForm.severityLevels.length > 0) {
        filterParts.push(`${alertForm.severityLevels.join(', ')} logs`)
    }
    if (alertForm.serviceNames.length > 0) {
        filterParts.push(`from ${alertForm.serviceNames.join(', ')}`)
    }
    if (alertForm.filterGroup.values.length > 0) {
        const attributeCount = alertForm.filterGroup.values.length
        filterParts.push(`${attributeCount} ${attributeCount === 1 ? 'attribute filter' : 'attribute filters'}`)
    }

    return {
        fires: `count ${alertForm.thresholdOperator} ${alertForm.thresholdCount} in the last ${alertForm.windowMinutes} minutes`,
        cadence: '',
        notifies: destinations.length
            ? `${destinations.length} ${destinations.length === 1 ? 'destination' : 'destinations'}`
            : '',
        filters: filterParts.join(' '),
    }
}
