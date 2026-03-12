import { useValues } from 'kea'

import { errorTrackingInsightsLogic } from './errorTrackingInsightsLogic'
import { TableCard } from './TableCard'

interface BrowserError {
    browser: string
    errorCount: number
    sessionCount: number
    errorRate: number
}

export function ErrorsByBrowser(): JSX.Element {
    const { errorsByBrowser, errorsByBrowserLoading } = useValues(errorTrackingInsightsLogic)

    const rows = (errorsByBrowser ?? []) as BrowserError[]

    return (
        <TableCard
            title="Error rate by browser"
            description="Which browsers experience the most crashes"
            loading={errorsByBrowserLoading}
        >
            {rows.length === 0 ? (
                <div className="flex items-center justify-center h-full text-secondary text-sm">No data</div>
            ) : (
                <table className="w-full">
                    <thead>
                        <tr className="text-xs text-secondary border-b">
                            <th className="text-left font-medium py-1.5 px-2">Browser</th>
                            <th className="text-right font-medium py-1.5 px-2">Errors</th>
                            <th className="text-right font-medium py-1.5 px-2">Sessions</th>
                            <th className="text-right font-medium py-1.5 px-2">Error rate</th>
                        </tr>
                    </thead>
                    <tbody>
                        {rows.map((row, i) => (
                            <tr key={i} className="border-b last:border-b-0 hover:bg-surface-secondary">
                                <td className="py-1.5 px-2 text-sm font-medium">{row.browser || 'Unknown'}</td>
                                <td className="py-1.5 px-2 text-sm text-right">{row.errorCount}</td>
                                <td className="py-1.5 px-2 text-sm text-right text-secondary">{row.sessionCount}</td>
                                <td className="py-1.5 px-2 text-right">
                                    <span
                                        className={`text-sm font-medium ${
                                            row.errorRate > 10
                                                ? 'text-danger'
                                                : row.errorRate > 5
                                                  ? 'text-warning'
                                                  : 'text-success'
                                        }`}
                                    >
                                        {row.errorRate.toFixed(1)}%
                                    </span>
                                </td>
                            </tr>
                        ))}
                    </tbody>
                </table>
            )}
        </TableCard>
    )
}
