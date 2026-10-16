import { useMemo } from 'react'

import { FunnelChart } from '@posthog/quill-charts'
import type { FunnelChartConfig, Series } from '@posthog/quill-charts'

import { useChartTheme } from 'lib/charts/hooks'
import { Text } from 'lib/ui/quill'

import type { SuppressedEventsIssue } from '../../recommendations/types'
import { share } from '../impactFormat'
import { SignalHeadline } from './SignalHeadline'
import { useImpactPalette } from './useImpactPalette'

const FIRST_STEP = 'On the page'

const FUNNEL_CONFIG: FunnelChartConfig = {
    hideValueAxis: true,
    showGrid: false,
    barCornerRadius: 3,
    chartMinHeight: 56,
    margins: { top: 2, right: 0, bottom: 2, left: 0 },
}

// A two-step funnel from the page to the event the error suppresses most, with the usual path and the path with the
// error side by side, so it reads like the product's own funnels.
export function SuppressedEventsSignal({ issue }: { issue: SuppressedEventsIssue }): JSX.Element {
    const palette = useImpactPalette()
    const theme = useChartTheme()
    const top = issue.events[0]
    const steps = useMemo(() => (top ? [FIRST_STEP, top.event] : []), [top])
    const series = useMemo<Series[]>(
        () =>
            top
                ? [
                      { key: 'usual', label: 'Usual', color: palette.ink, data: [100, top.comparison_share * 100] },
                      {
                          key: 'error',
                          label: 'With the error',
                          color: palette.hurting,
                          data: [100, top.issue_share * 100],
                      },
                  ]
                : [],
        [palette, top]
    )
    if (!top) {
        return <SignalHeadline value="-" caption="no suppressed events" />
    }
    return (
        <div className="flex h-24 w-full max-w-64 flex-col">
            <FunnelChart
                steps={steps}
                series={series}
                theme={theme}
                config={FUNNEL_CONFIG}
                stepFooter={(stepIndex) =>
                    stepIndex === 0 ? (
                        <Text render={<span />} size="xs" variant="muted">
                            {FIRST_STEP}
                        </Text>
                    ) : (
                        <div className="flex min-w-0 flex-col" title={top.event}>
                            <Text render={<span />} size="xs" variant="muted" className="truncate font-mono">
                                {top.event}
                            </Text>
                            <Text render={<span />} size="xs" weight="semibold" className="tabular-nums">
                                {`${share(top.comparison_share)} → ${share(top.issue_share)}`}
                            </Text>
                        </div>
                    )
                }
            />
        </div>
    )
}
