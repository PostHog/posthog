import { Button } from '@posthog/quill'
// PROTOTYPE (throwaway): where people go after they click a link in a message, and what they do within 7 days.
// Connects messaging to product data, the part other email tools cannot show.
import { SankeyChart } from '@posthog/quill-charts'

import { useChartTheme } from 'lib/charts/hooks'

import { ChartCard } from './ChartCard'
import { EmptyInsight } from './EmptyInsight'
import { AFTER_CLICK_LINKS, AFTER_CLICK_NODES, AFTER_CLICK_STAGES } from './insightsData'
import { formatCount } from './prototypeData'

const CONFIG = { columnLabels: AFTER_CLICK_STAGES, valueFormatter: formatCount }

export function AfterClickCard({ noSends }: { noSends: boolean }): JSX.Element {
    const theme = useChartTheme()
    return (
        <ChartCard
            title="What people do after a click"
            description="Within 7 days of the click"
            action={noSends ? null : <Button variant="link">Watch 1,214 replays</Button>}
        >
            {noSends ? (
                <EmptyInsight
                    title="See where a click leads"
                    detail="When people click a link in a message, this shows the page they land on and what they do in the next 7 days."
                />
            ) : (
                <div className="flex h-72 flex-col">
                    <SankeyChart nodes={AFTER_CLICK_NODES} links={AFTER_CLICK_LINKS} theme={theme} config={CONFIG} />
                </div>
            )}
        </ChartCard>
    )
}
