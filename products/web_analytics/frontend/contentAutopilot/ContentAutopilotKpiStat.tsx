import { PageStatCard } from '../pageReports/PageStatCard'
import { ContentAutopilotKpiDelta } from './ContentAutopilotKpiDelta'
import type { KpiCardContent } from './promptReport'

export const ContentAutopilotKpiStat = ({
    label,
    description,
    value,
    note,
    delta,
    onClick,
    'data-attr': dataAttr,
}: KpiCardContent & {
    label: string
    description: string
    onClick?: () => void
    'data-attr': string
}): JSX.Element => (
    <PageStatCard
        label={label}
        aside={delta ? <ContentAutopilotKpiDelta delta={delta} /> : null}
        value={value}
        detail={note}
        loading={false}
        tooltip={description}
        onClick={onClick}
        data-attr={dataAttr}
    />
)
