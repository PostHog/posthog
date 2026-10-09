import { DEFAULT_SEVERITY_LEVELS, type LogsAlertFormType } from './logsAlertFormLogic'

/**
 * Prefills a new alert from one log row: match the row's service and severity, and name the alert
 * after them. A field the log does not carry keeps the form default.
 */
export function buildAlertSeedFromLog(log: {
    severity_text: string
    resource_attributes?: Record<string, unknown>
}): Partial<LogsAlertFormType> {
    const serviceName = String(log.resource_attributes?.['service.name'] ?? '').trim()
    const severity = (log.severity_text ?? '').trim().toLowerCase()
    const knownSeverity = DEFAULT_SEVERITY_LEVELS.find((level) => level === severity)

    const seed: Partial<LogsAlertFormType> = {}
    if (serviceName) {
        seed.serviceNames = [serviceName]
    }
    if (knownSeverity) {
        seed.severityLevels = [knownSeverity]
    }
    const nameParts = [serviceName, knownSeverity].filter(Boolean)
    if (nameParts.length) {
        seed.name = `${nameParts.join(' ')} logs`
    }
    return seed
}
