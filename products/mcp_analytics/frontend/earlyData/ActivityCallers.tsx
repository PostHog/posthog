import { useValues } from 'kea'

import { useChartTheme } from 'lib/charts/hooks'

import { HarnessBarChart } from '../dashboard/HarnessBarChart'
import { ModelBarChart } from '../dashboard/ModelBarChart'
import { ACTIVITY_FILTERS, mcpEarlyDataLogic } from './mcpEarlyDataLogic'

// The same two cards as the dashboard's Usage section, over the activity tab's fixed window.
export function ActivityCallers(): JSX.Element {
    const { harnessRows, harnessRowsLoading, modelRows, hasModelData } = useValues(mcpEarlyDataLogic)
    const theme = useChartTheme()

    return (
        <section className="@container flex min-w-0 flex-col gap-2" data-attr="mcp-analytics-activity-callers">
            <h3 className="mb-0 text-sm font-semibold">Who is calling your server</h3>
            <div className="grid min-w-0 grid-cols-1 gap-4 @3xl:grid-cols-2" data-quill>
                <HarnessBarChart rows={harnessRows} loading={harnessRowsLoading} theme={theme} />
                {hasModelData ? <ModelBarChart rows={modelRows} theme={theme} filters={ACTIVITY_FILTERS} /> : null}
            </div>
        </section>
    )
}
