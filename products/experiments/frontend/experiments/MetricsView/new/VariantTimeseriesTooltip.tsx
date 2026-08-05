import { useValues } from 'kea'

import { IconCalendar, IconClock, IconHome, IconLaptop } from '@posthog/icons'

import { dayjs } from 'lib/dayjs'
import { IconWeb } from 'lib/lemon-ui/icons'
import { shortTimeZone } from 'lib/utils/timezones'
import { teamLogic } from 'scenes/teamLogic'

const DATE_FORMAT = 'MMM D, YYYY'
const DATETIME_FORMAT = 'MMM D, YYYY h:mm A'

const formatPercent = (value: number | null): string => (value === null ? '—' : `${(value * 100).toFixed(2)}%`)

export interface VariantTimeseriesTooltipProps {
    date: string
    delta: number | null
    lowerBound: number | null
    upperBound: number | null
    isRatioMetric: boolean
    exposures?: number
    denominator?: number
    significant?: boolean
    hasRealData: boolean
    /** When the timeseries was computed (ISO string), or null if unknown. */
    computedAt: string | null
}

function TooltipRow({ label, value }: { label: string; value: React.ReactNode }): JSX.Element {
    return (
        <div className="flex items-center justify-between gap-4">
            <span className="text-secondary">{label}</span>
            <span className="font-medium tabular-nums">{value}</span>
        </div>
    )
}

function CalculatedAtRow({
    icon,
    label,
    caption,
    value,
}: {
    icon: React.ReactNode
    label: string
    caption?: string
    value: string
}): JSX.Element {
    return (
        <div className="flex items-center gap-1.5">
            <span className="text-secondary text-base shrink-0">{icon}</span>
            <span className="text-secondary">{label}</span>
            {caption && <span className="text-secondary text-[0.6875rem]">{caption}</span>}
            <span className="ml-auto font-medium tabular-nums">{value}</span>
        </div>
    )
}

/**
 * Standalone, fully formattable tooltip for the variant timeseries chart.
 * Rendered into the shared insight-tooltip DOM via the chart's `external` callback.
 */
export function VariantTimeseriesTooltip({
    date,
    delta,
    lowerBound,
    upperBound,
    isRatioMetric,
    exposures,
    denominator,
    significant,
    hasRealData,
    computedAt,
}: VariantTimeseriesTooltipProps): JSX.Element {
    const { currentTeam } = useValues(teamLogic)

    const computed = computedAt ? dayjs(computedAt) : null
    const projectTimezone = currentTeam?.timezone
    const computedDate = computed?.toDate()

    return (
        <div className="bg-surface-primary border border-primary rounded shadow-md text-[0.8125rem] min-w-[15rem] overflow-hidden">
            <div className="px-3 py-2 border-b border-primary font-semibold flex items-center gap-1.5">
                <IconCalendar className="text-secondary text-base" />
                {dayjs(date).format(DATE_FORMAT)}
            </div>

            <div className="px-3 py-2 flex flex-col gap-1">
                <TooltipRow label="Delta" value={formatPercent(delta)} />
                <TooltipRow
                    label="Confidence interval"
                    value={`${formatPercent(lowerBound)} → ${formatPercent(upperBound)}`}
                />
                {isRatioMetric
                    ? denominator !== undefined && (
                          <TooltipRow label="Denominator" value={denominator.toLocaleString()} />
                      )
                    : exposures !== undefined && <TooltipRow label="Exposures" value={exposures.toLocaleString()} />}
                {significant !== undefined && (
                    <TooltipRow
                        label="Significant"
                        value={
                            <span className={significant ? 'text-success' : 'text-secondary'}>
                                {significant ? 'Yes' : 'No'}
                            </span>
                        }
                    />
                )}
            </div>

            {!hasRealData && (
                <div className="px-3 py-1.5 border-t border-primary text-warning text-xs flex items-center gap-1.5">
                    <IconClock className="text-base shrink-0" />
                    Data pending — showing last known value
                </div>
            )}

            {computed && (
                <div className="px-3 py-2 border-t border-primary bg-surface-secondary flex flex-col gap-1 text-xs">
                    <div className="text-secondary uppercase tracking-wide text-[0.6875rem] font-semibold mb-0.5">
                        Calculated at
                    </div>
                    {projectTimezone && (
                        <CalculatedAtRow
                            icon={<IconHome />}
                            label="Project"
                            caption={shortTimeZone(projectTimezone, computedDate) ?? projectTimezone}
                            value={computed.tz(projectTimezone).format(DATETIME_FORMAT)}
                        />
                    )}
                    <CalculatedAtRow
                        icon={<IconLaptop />}
                        label="Your device"
                        caption={shortTimeZone(undefined, computedDate) ?? ''}
                        value={computed.format(DATETIME_FORMAT)}
                    />
                    {projectTimezone !== 'UTC' && (
                        <CalculatedAtRow
                            icon={<IconWeb />}
                            label="UTC"
                            caption="UTC"
                            value={computed.tz('UTC').format(DATETIME_FORMAT)}
                        />
                    )}
                </div>
            )}
        </div>
    )
}
