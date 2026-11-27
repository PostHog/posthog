import { Tooltip, TooltipContent, TooltipTrigger, cn } from '@posthog/quill'
import { Metric, MetricHeader, MetricSubtitle, MetricTitle, MetricValue } from '@posthog/quill-components/metric'

import { ContentAutopilotKpiDelta } from './ContentAutopilotKpiDelta'
import type { KpiCardContent } from './promptReport'

const TILE_CLASS_NAME = 'flex h-full w-full min-w-0 flex-col py-3 text-start'

export const ContentAutopilotKpiStat = ({
    label,
    description,
    value,
    note,
    delta,
    onClick,
    'data-attr': dataAttr,
}: Pick<KpiCardContent, 'value'> &
    Partial<Pick<KpiCardContent, 'note' | 'delta'>> & {
        label: string
        description: string
        onClick?: () => void
        'data-attr': string
    }): JSX.Element => (
    <div className="min-w-0">
        <Tooltip>
            <TooltipTrigger
                render={
                    onClick ? (
                        <button
                            type="button"
                            className={cn(
                                TILE_CLASS_NAME,
                                'cursor-pointer transition-colors hover:bg-fill-hover motion-reduce:transition-none'
                            )}
                            onClick={onClick}
                            data-attr={dataAttr}
                        />
                    ) : (
                        <div className={TILE_CLASS_NAME} data-attr={dataAttr} />
                    )
                }
            >
                {/* The value arrives formatted, such as "Not cited", so the headline renders it as children and
                    `value` only keeps Metric from rendering nothing. MetricDelta would draw "No change" as a rise. */}
                <Metric value={0} change={null}>
                    <MetricHeader className="flex-wrap items-center">
                        <MetricTitle className="font-normal text-muted-foreground">{label}</MetricTitle>
                        {delta ? <ContentAutopilotKpiDelta delta={delta} /> : null}
                    </MetricHeader>
                    <MetricValue className="text-2xl font-semibold" translate="no">
                        {value}
                    </MetricValue>
                    {note ? (
                        <MetricSubtitle className="text-xs text-muted-foreground opacity-100">{note}</MetricSubtitle>
                    ) : null}
                </Metric>
            </TooltipTrigger>
            <TooltipContent side="bottom" className="max-w-80">
                {description}
            </TooltipContent>
        </Tooltip>
    </div>
)
