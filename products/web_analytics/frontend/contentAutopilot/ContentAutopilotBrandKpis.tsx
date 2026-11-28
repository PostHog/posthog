import type { BrandDetailKpi } from './brandDetail'
import { ContentAutopilotKpiStat } from './ContentAutopilotKpiStat'
import { ContentAutopilotStatStrip } from './ContentAutopilotStatStrip'

/** A brand's headline figures in the AI visibility KPI strip: the range's value against the range before, with the
 *  range's last day in each tile's tooltip. */
export const ContentAutopilotBrandKpis = ({ kpis }: { kpis: BrandDetailKpi[] }): JSX.Element => (
    <ContentAutopilotStatStrip
        className="grid-cols-2 @3xl/brand-page:grid-cols-4"
        data-attr="content-autopilot-brand-kpis"
    >
        {kpis.map((kpi) => (
            <ContentAutopilotKpiStat
                key={kpi.key}
                label={kpi.label}
                description={kpi.latest ? `${kpi.description} ${kpi.latest}` : kpi.description}
                value={kpi.formatted ?? kpi.emptyMessage}
                note={kpi.subtitle ?? undefined}
                delta={kpi.delta}
                data-attr={`content-autopilot-brand-kpi-${kpi.key}`}
            />
        ))}
    </ContentAutopilotStatStrip>
)
