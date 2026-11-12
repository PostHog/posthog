import { Fragment, ReactNode } from 'react'

import { IconInfo, IconTestTube } from '@posthog/icons'
import { Button, Separator, Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'

import { FunnelVizType } from '~/types'

import { FunnelStepsPicker } from './filters/FunnelStepsPicker'

interface QuillFunnelCanvasLabelProps {
    funnelVizType: FunnelVizType
    totalRate: string
    totalRateTooltip: string
    medianTime: string | null
    medianTimeLabel: string
    medianTimeTooltip: string
    onShowTimeToConvert: () => void
    experimentUrl: string | null
    experimentTooltip: string
    onRunExperiment: () => void
}

function InfoLabel({ tooltip, children }: { tooltip: string; children: ReactNode }): JSX.Element {
    return (
        <span className="flex items-center gap-1 text-muted-foreground">
            <Tooltip>
                <TooltipTrigger render={<span className="inline-flex text-base" />}>
                    <IconInfo />
                </TooltipTrigger>
                <TooltipContent className="max-w-xs">{tooltip}</TooltipContent>
            </Tooltip>
            {children}
        </span>
    )
}

export function QuillFunnelCanvasLabel({
    funnelVizType,
    totalRate,
    totalRateTooltip,
    medianTime,
    medianTimeLabel,
    medianTimeTooltip,
    onShowTimeToConvert,
    experimentUrl,
    experimentTooltip,
    onRunExperiment,
}: QuillFunnelCanvasLabelProps): JSX.Element {
    const isTimeToConvert = funnelVizType === FunnelVizType.TimeToConvert

    const labels: ReactNode[] = []
    if (funnelVizType === FunnelVizType.Steps) {
        labels.push(
            <>
                <InfoLabel tooltip={totalRateTooltip}>Total conversion rate:</InfoLabel>
                <span className="font-semibold">{totalRate}</span>
            </>
        )
    }
    if (funnelVizType !== FunnelVizType.Trends && medianTime !== null) {
        labels.push(
            <>
                <InfoLabel tooltip={medianTimeTooltip}>{medianTimeLabel}</InfoLabel>
                {isTimeToConvert && <FunnelStepsPicker />}
                <span className="text-muted-foreground">:</span>
                {isTimeToConvert ? (
                    <span className="font-semibold">{medianTime}</span>
                ) : (
                    <Button variant="link" size="inline" className="font-semibold" onClick={onShowTimeToConvert}>
                        {medianTime}
                    </Button>
                )}
            </>
        )
    }
    if (funnelVizType === FunnelVizType.Trends) {
        labels.push(
            <>
                <span className="text-muted-foreground">Conversion rate</span>
                <FunnelStepsPicker />
            </>
        )
    }
    if (experimentUrl) {
        labels.push(
            <Button
                variant="outline"
                size="sm"
                tooltip={experimentTooltip}
                onClick={onRunExperiment}
                render={<LinkPrimitive to={experimentUrl} />}
                data-attr="create-experiment-from-insight"
            >
                <IconTestTube />
                Run experiment
            </Button>
        )
    }

    return (
        <div className="flex items-center gap-1">
            {labels.map((label, index) => (
                <Fragment key={index}>
                    {index > 0 && <Separator orientation="vertical" className="mx-1 h-3.5 self-center" />}
                    {label}
                </Fragment>
            ))}
        </div>
    )
}
