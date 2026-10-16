import { useMemo } from 'react'

import { Sparkline } from '@posthog/quill-charts'
import type { Series } from '@posthog/quill-charts'

import { useChartTheme } from 'lib/charts/hooks'
import { Tooltip, TooltipContent, TooltipTrigger } from 'lib/ui/quill'

import type { FlowDropIncident, FlowDropIssue } from '../../recommendations/types'
import { share, shortPath } from '../impactFormat'
import { SignalHeadline } from './SignalHeadline'
import { useImpactPalette } from './useImpactPalette'

export interface FlowDropSignalProps {
    issue: FlowDropIssue
    incident: FlowDropIncident | null
}

const SPARKLINE_HEIGHT = 28

// The hourly rate of visits that got through, over a dashed line for the usual rate, with the broken hours in the
// broken color. The broken line reaches one hour to each side so that a one-hour break still draws as a dip.
function hourlySeries(incident: FlowDropIncident, colors: { usual: string; rate: string; broken: string }): Series[] {
    const rates = incident.hourly.map((hour) => hour.rate ?? Number.NaN)
    const brokenFrom = incident.hourly.findIndex((hour) => hour.hour === incident.hour)
    const brokenTo = brokenFrom + incident.hours - 1
    return [
        {
            key: 'usual',
            label: 'Usual',
            data: incident.hourly.map((hour) => hour.usual_rate ?? Number.NaN),
            color: colors.usual,
            stroke: { pattern: [3, 3] },
        },
        { key: 'rate', label: 'Got through', data: rates, color: colors.rate },
        {
            key: 'broken',
            label: 'Broken',
            data: rates.map((rate, index) =>
                brokenFrom >= 0 && index >= brokenFrom - 1 && index <= brokenTo + 1 ? rate : Number.NaN
            ),
            color: colors.broken,
        },
    ]
}

export function FlowDropSignal({ issue, incident }: FlowDropSignalProps): JSX.Element {
    const palette = useImpactPalette()
    const theme = useChartTheme()
    const series = useMemo(
        () =>
            incident
                ? hourlySeries(incident, { usual: palette.neutral, rate: palette.ink, broken: palette.broken })
                : [],
        [incident, palette]
    )
    const labels = useMemo(() => incident?.hourly.map((hour) => hour.hour) ?? [], [incident])
    return (
        <Tooltip>
            <TooltipTrigger render={<div tabIndex={0} className="flex w-full max-w-64 flex-col gap-1.5" />}>
                <SignalHeadline
                    value={share(issue.rate)}
                    caption={`got through, usual ${share(issue.usual_rate)}`}
                    tone="destructive"
                />
                {incident && <Sparkline series={series} labels={labels} theme={theme} height={SPARKLINE_HEIGHT} />}
            </TooltipTrigger>
            <TooltipContent>
                {`In the worst hour ${share(issue.rate)} of visits got from ${shortPath(issue.from_path)} to ${shortPath(issue.to_path)} within 30 minutes. It is usually ${share(issue.usual_rate)} at that hour. Visits that got this error on the first page got through ${share(issue.exposed_finish_rate)} of the time, against ${share(issue.unexposed_finish_rate)} for the other visits. This is linked to the drop, but does not prove the error caused it.`}
            </TooltipContent>
        </Tooltip>
    )
}
