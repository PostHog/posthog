export function opensRunLogs(searchParams: Record<string, any>): boolean {
    return searchParams.tab === 'sends' && Object.keys(searchParams).some(isRunLogFilter)
}

export function withoutRunLogFilters(searchParams: Record<string, any>): Record<string, any> {
    return Object.fromEntries(Object.entries(searchParams).filter(([param]) => !isRunLogFilter(param)))
}

function isRunLogFilter(param: string): boolean {
    return param.startsWith('inv_')
}
