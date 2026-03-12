import { useValues } from 'kea'

import { LemonButton } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { errorTrackingInsightsLogic } from './errorTrackingInsightsLogic'
import { TableCard } from './TableCard'

interface FlagErrorRow {
    flag: string
    totalSessions: number
    errorSessions: number
    errorRate: number
}

export function ErrorsByFeatureFlag(): JSX.Element {
    const { errorsByFeatureFlag, errorsByFeatureFlagLoading } = useValues(errorTrackingInsightsLogic)

    const rows = (errorsByFeatureFlag ?? []) as FlagErrorRow[]

    return (
        <TableCard
            title="Error rate by feature flag"
            description="% of sessions with errors per active flag"
            loading={errorsByFeatureFlagLoading}
        >
            {rows.length === 0 ? (
                <div className="flex items-center justify-center h-full text-secondary text-sm">No data</div>
            ) : (
                <table className="w-full">
                    <thead>
                        <tr className="text-xs text-secondary border-b">
                            <th className="text-left font-medium py-1.5 px-2">Feature flag</th>
                            <th className="text-right font-medium py-1.5 px-2">Sessions</th>
                            <th className="text-right font-medium py-1.5 px-2">Error sessions</th>
                            <th className="text-right font-medium py-1.5 px-2">Error rate</th>
                            <th className="text-right font-medium py-1.5 px-2">Actions</th>
                        </tr>
                    </thead>
                    <tbody>
                        {rows.map((row, i) => (
                            <tr key={i} className="border-b last:border-b-0 hover:bg-surface-secondary">
                                <td
                                    className="py-1.5 px-2 text-sm font-mono text-xs max-w-48 truncate"
                                    title={row.flag}
                                >
                                    {row.flag}
                                </td>
                                <td className="py-1.5 px-2 text-sm text-right text-secondary">{row.totalSessions}</td>
                                <td className="py-1.5 px-2 text-sm text-right">{row.errorSessions}</td>
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
                                <td className="py-1.5 px-2 text-right">
                                    <LemonButton
                                        type="secondary"
                                        size="xsmall"
                                        to={urls.featureFlags() + `?search=${encodeURIComponent(row.flag)}`}
                                        targetBlank
                                    >
                                        View flag
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
