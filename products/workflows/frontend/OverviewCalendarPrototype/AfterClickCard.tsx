import { Button } from '@posthog/quill'
// PROTOTYPE (throwaway): where people go after they click a link in a message, and what they do within 7 days.
// Connects messaging to product data, the part other email tools cannot show.
import { SankeyChart } from '@posthog/quill-charts'

import { useChartTheme } from 'lib/charts/hooks'

import { ChartCard } from './ChartCard'
import { AFTER_CLICK_LINKS, AFTER_CLICK_NODES, AFTER_CLICK_STAGES } from './insightsData'
import { formatCount } from './prototypeData'

const CONFIG = { columnLabels: AFTER_CLICK_STAGES, valueFormatter: formatCount }

export function AfterClickCard(): JSX.Element {
    const theme = useChartTheme()
    return (
        <ChartCard
            title="What people do after a click"
            description="Last 30 days, all messages. Within 7 days of the click."
            action={<Button variant="link">Watch 1,214 replays</Button>}
        >
            <div className="flex h-72 flex-col">
                <SankeyChart nodes={AFTER_CLICK_NODES} links={AFTER_CLICK_LINKS} theme={theme} config={CONFIG} />
            </div>
        </ChartCard>
    )
}
