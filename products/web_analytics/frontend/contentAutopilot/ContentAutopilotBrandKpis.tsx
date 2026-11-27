import { Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill'

import { AnalyticsMetricCard } from 'lib/components/AnalyticsMetricCard/AnalyticsMetricCard'

import type { BrandDetailKpi } from './brandDetail'

/** A brand's headline figures as Web analytics tiles: the range's value against the range before, with the
 *  range's last day in the title's tooltip. */
export const ContentAutopilotBrandKpis = ({ kpis }: { kpis: BrandDetailKpi[] }): JSX.Element => (
    <div className="grid grid-cols-[repeat(auto-fit,minmax(10rem,1fr))] gap-2" data-attr="content-autopilot-brand-kpis">
        {kpis.map((kpi) => (
            <AnalyticsMetricCard
                key={kpi.key}
                dataAttr={`content-autopilot-brand-kpi-${kpi.key}`}
                title={
                    <Tooltip>
                        <TooltipTrigger render={<span className="cursor-help" />}>{kpi.label}</TooltipTrigger>
                        <TooltipContent className="max-w-80">
                            <span className="flex flex-col gap-1">
                                <span>{kpi.description}</span>
                                {kpi.latest ? <span className="tabular-nums">{kpi.latest}</span> : null}
                            </span>
                        </TooltipContent>
                    </Tooltip>
                }
                value={kpi.value ?? undefined}
                emptyMessage={kpi.emptyMessage}
                formatValue={() => kpi.formatted ?? ''}
                change={kpi.change === null || kpi.change === 0 ? null : { value: kpi.change }}
                formatChange={() => kpi.changeLabel ?? ''}
                goodDirection={kpi.goodDirection}
                subtitle={kpi.subtitle ?? undefined}
            />
        ))}
    </div>
)
