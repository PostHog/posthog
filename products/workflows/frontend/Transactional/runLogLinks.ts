// `tab=sends` named the run logs before an email page had a list of sends, and a metric drill added `inv_` filters to
// it. A link like that still opens the run logs.
export function opensRunLogs(searchParams: Record<string, any>): boolean {
    return searchParams.tab === 'sends' && Object.keys(searchParams).some(isRunLogFilter)
}

// Sends drops the run log filters, so a reload of the Sends tab doesn't read as an old run log link.
export function withoutRunLogFilters(searchParams: Record<string, any>): Record<string, any> {
    return Object.fromEntries(Object.entries(searchParams).filter(([param]) => !isRunLogFilter(param)))
}

function isRunLogFilter(param: string): boolean {
    return param.startsWith('inv_')
}
