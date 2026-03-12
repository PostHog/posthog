import { useValues } from 'kea'

import { LemonButton } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { PropertyFilterType, PropertyOperator } from '~/types'

import { errorTrackingInsightsLogic } from './errorTrackingInsightsLogic'
import { TableCard } from './TableCard'

interface PageErrorRate {
    url: string
    pageviews: number
    errors: number
    errorRate: number
}

export function ErrorsByPage(): JSX.Element {
    const { errorsByPage, errorsByPageLoading } = useValues(errorTrackingInsightsLogic)

    const rows = (errorsByPage ?? []) as PageErrorRate[]

    return (
        <TableCard
            title="Error rate by page"
            description="% of page visits that resulted in an exception"
            loading={errorsByPageLoading}
        >
            {rows.length === 0 ? (
                <div className="flex items-center justify-center h-full text-secondary text-sm">No data</div>
            ) : (
                <table className="w-full">
                    <thead>
                        <tr className="text-xs text-secondary border-b">
                            <th className="text-left font-medium py-1.5 px-2">Page URL</th>
                            <th className="text-right font-medium py-1.5 px-2">Visits</th>
                            <th className="text-right font-medium py-1.5 px-2">Errors</th>
                            <th className="text-right font-medium py-1.5 px-2">Error rate</th>
                            <th className="text-right font-medium py-1.5 px-2">Actions</th>
                        </tr>
                    </thead>
                    <tbody>
                        {rows.map((row, i) => (
                            <tr key={i} className="border-b last:border-b-0 hover:bg-surface-secondary">
                                <td className="py-1.5 px-2 max-w-48 truncate font-mono text-xs" title={row.url}>
                                    {formatUrl(row.url)}
                                </td>
                                <td className="py-1.5 px-2 text-sm text-right text-secondary">{row.pageviews}</td>
                                <td className="py-1.5 px-2 text-sm text-right">{row.errors}</td>
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
                                <td className="py-1.5 px-2 text-right w-px whitespace-nowrap">
                                    <LemonButton
                                        type="secondary"
                                        size="xsmall"
                                        to={urls.errorTracking({
                                            activeTab: 'issues',
                                            filterGroup: {
                                                type: 'AND',
                                                values: [
                                                    {
                                                        type: 'AND',
                                                        values: [
                                                            {
                                                                type: PropertyFilterType.Event,
                                                                key: '$current_url',
                                                                value: row.url,
                                                                operator: PropertyOperator.Exact,
                                                            },
                                                        ],
                                                    },
                                                ],
                                            },
                                        })}
                                        targetBlank
                                    >
                                        View issues
                                    </LemonButton>
                                </td>
                            </tr>
                        ))}
                    </tbody>
                </table>
            )}
        </TableCard>
    )
}

function formatUrl(url: string): string {
    try {
        const parsed = new URL(url)
        return parsed.pathname + parsed.search
    } catch {
        return url
    }
}
