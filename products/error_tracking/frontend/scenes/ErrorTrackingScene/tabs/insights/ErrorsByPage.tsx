import { useValues } from 'kea'

import { LemonButton } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { PropertyFilterType, PropertyOperator } from '~/types'

import { errorTrackingInsightsLogic } from './errorTrackingInsightsLogic'
import { TableCard } from './TableCard'

interface PageError {
    url: string
    errorCount: number
    userCount: number
}

export function ErrorsByPage(): JSX.Element {
    const { errorsByPage, errorsByPageLoading } = useValues(errorTrackingInsightsLogic)

    const rows = (errorsByPage ?? []) as PageError[]

    return (
        <TableCard title="Errors by page" description="Pages with the most exceptions" loading={errorsByPageLoading}>
            {rows.length === 0 ? (
                <div className="flex items-center justify-center h-full text-secondary text-sm">No data</div>
            ) : (
                <table className="w-full">
                    <thead>
                        <tr className="text-xs text-secondary border-b">
                            <th className="text-left font-medium py-1.5 px-2">Page URL</th>
                            <th className="text-right font-medium py-1.5 px-2">Errors</th>
                            <th className="text-right font-medium py-1.5 px-2">Users</th>
                            <th className="text-right font-medium py-1.5 px-2">Actions</th>
                        </tr>
                    </thead>
                    <tbody>
                        {rows.map((row, i) => (
                            <tr key={i} className="border-b last:border-b-0 hover:bg-surface-secondary">
                                <td className="py-1.5 px-2 text-sm max-w-60 truncate font-mono text-xs" title={row.url}>
                                    {formatUrl(row.url)}
                                </td>
                                <td className="py-1.5 px-2 text-sm text-right font-medium">{row.errorCount}</td>
                                <td className="py-1.5 px-2 text-sm text-right text-secondary">{row.userCount}</td>
                                <td className="py-1.5 px-2 text-right">
                                    <LemonButton
                                        type="secondary"
                                        size="xsmall"
                                        to={urls.errorTracking({
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
                                        View errors
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
