import { useMemo } from 'react'

import { FunnelChart } from '@posthog/quill-charts'
import type { FunnelChartConfig, Series } from '@posthog/quill-charts'

import { useChartTheme } from 'lib/charts/hooks'
import { Text, cn } from 'lib/ui/quill'

import type { FunnelStepIncident, FunnelStepIssue } from '../../recommendations/types'
import { share, shortPath } from '../impactFormat'
import { SignalHeadline } from './SignalHeadline'
import { useImpactPalette } from './useImpactPalette'

const FUNNEL_CONFIG: FunnelChartConfig = {
    hideValueAxis: true,
    showGrid: false,
    barCornerRadius: 3,
    chartMinHeight: 48,
    margins: { top: 2, right: 0, bottom: 2, left: 0 },
}

export interface FunnelStepSignalProps {
    issue: FunnelStepIssue
    incident: FunnelStepIncident | null
}

// The chain as a funnel, the usual hour next to the worst hour, with the step that broke marked under its second page.
export function FunnelStepSignal({ issue, incident }: FunnelStepSignalProps): JSX.Element {
    const palette = useImpactPalette()
    const theme = useChartTheme()
    const pages = useMemo(() => issue.pages.map(shortPath), [issue.pages])
    const series = useMemo<Series[]>(
        () =>
            incident
                ? [
                      {
                          key: 'usual',
                          label: 'Usual',
                          color: palette.ink,
                          data: [100, ...incident.steps.map((step) => step.usual_reached_rate * 100)],
                      },
                      {
                          key: 'worst',
                          label: 'Worst hour',
                          color: palette.broken,
                          data: [100, ...incident.steps.map((step) => step.reached_rate * 100)],
                      },
                  ]
                : [],
        [incident, palette]
    )
    const brokenStep = incident?.steps[issue.broken_step]
    return (
        <div className="flex w-full max-w-64 flex-col gap-1">
            <SignalHeadline
                value={share(issue.rate)}
                caption={`got through all ${pages.length} pages, usual ${share(issue.usual_rate)}`}
                tone="destructive"
            />
            {incident && incident.steps.length === pages.length - 1 && (
                <div className="flex h-20 w-full flex-col">
                    <FunnelChart
                        steps={pages}
                        series={series}
                        theme={theme}
                        config={FUNNEL_CONFIG}
                        stepFooter={(stepIndex) => {
                            const broken = stepIndex === issue.broken_step + 1
                            return (
                                <Text
                                    render={<span />}
                                    size="xs"
                                    weight={broken ? 'semibold' : undefined}
                                    variant={broken ? undefined : 'muted'}
                                    className={cn(
                                        'block truncate tabular-nums',
                                        broken && 'text-destructive-foreground'
                                    )}
                                >
                                    {broken && brokenStep?.rate != null && brokenStep.usual_rate != null
                                        ? `${share(brokenStep.usual_rate)} → ${share(brokenStep.rate)}`
                                        : stepIndex + 1}
                                </Text>
                            )
                        }}
                    />
                </div>
            )}
            <Text
                render={<span />}
                size="xs"
                variant="muted"
                className="truncate"
                title={`${issue.from_path} → ${issue.to_path}`}
            >
                {`Step ${issue.broken_step + 1} ${incident?.clear ? 'broke' : 'fell most'}: ${shortPath(issue.from_path)} → ${shortPath(issue.to_path)}`}
            </Text>
        </div>
    )
}
