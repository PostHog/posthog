import { useValues } from 'kea'

import { errorTrackingInsightsLogic } from './errorTrackingInsightsLogic'
import { TableCard } from './TableCard'

interface NewVsReturningRow {
    label: string
    errorCount: number
    userCount: number
    errorsPerUser: number
}

export function ErrorsNewVsReturning(): JSX.Element {
    const { errorsNewVsReturning, errorsNewVsReturningLoading } = useValues(errorTrackingInsightsLogic)

    const rows = (errorsNewVsReturning ?? []) as NewVsReturningRow[]

    return (
        <TableCard
            title="Errors: new vs returning users"
            description="Are new users hitting more errors than returning ones?"
            loading={errorsNewVsReturningLoading}
        >
            {rows.length === 0 ? (
                <div className="flex items-center justify-center h-full text-secondary text-sm">No data</div>
            ) : (
                <table className="w-full">
                    <thead>
                        <tr className="text-xs text-secondary border-b">
                            <th className="text-left font-medium py-1.5 px-2">User type</th>
                            <th className="text-right font-medium py-1.5 px-2">Errors</th>
                            <th className="text-right font-medium py-1.5 px-2">Users</th>
                            <th className="text-right font-medium py-1.5 px-2">Errors / user</th>
                        </tr>
                    </thead>
                    <tbody>
                        {rows.map((row, i) => (
                            <tr key={i} className="border-b last:border-b-0 hover:bg-surface-secondary">
                                <td className="py-1.5 px-2 text-sm font-medium">{row.label}</td>
                                <td className="py-1.5 px-2 text-sm text-right">{row.errorCount}</td>
                                <td className="py-1.5 px-2 text-sm text-right text-secondary">{row.userCount}</td>
                                <td className="py-1.5 px-2 text-sm text-right font-medium">
                                    {row.errorsPerUser.toFixed(1)}
                                </td>
                            </tr>
                        ))}
                    </tbody>
                </table>
            )}
        </TableCard>
    )
}
