import Papa from 'papaparse'

import { ParsedLogMessage } from '../types'

// helper function to clean log message text for CSV export by replacing newlines with spaces
function cleanForCSV(value: string): string {
    return String(value ?? '')
        .replace(/\n/g, ' ')
        .replace(/\r/g, '')
}

export function logsToCSV(logs: ParsedLogMessage[]): string {
    const header = ['Timestamp', 'Level', 'Message']
    const rows = logs.map((log) => [
        cleanForCSV(log.timestamp),
        cleanForCSV(log.severity_text),
        cleanForCSV(log.cleanBody || log.body),
    ])

    // escapeFormulae: true prevents Excel from interpreting the data as formulas
    return Papa.unparse([header, ...rows], {
        escapeFormulae: true,
    })
}

export function logsToJSON(logs: ParsedLogMessage[]): string {
    const exportData = logs.map((log) => ({
        timestamp: log.timestamp,
        level: log.severity_text,
        message: log.parsedBody || log.cleanBody || log.body,
    }))

    return JSON.stringify(exportData, null, 2)
}
