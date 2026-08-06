import { getSeriesColor } from 'lib/colors'
import { PropertyIcon } from 'lib/components/PropertyIcon/PropertyIcon'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { humanFriendlyLargeNumber } from 'lib/utils/numbers'
import { BREAKDOWN_NULL_DISPLAY, BREAKDOWN_OTHER_DISPLAY, isNullBreakdown } from 'scenes/insights/utils'

import { BreakdownSinglePropertyStat } from './miniBreakdownsLogic'

interface BreakdownsStackedBarProps {
    properties: BreakdownSinglePropertyStat[]
    totalCount: number
    propertyName: string
    propertyLabel?: string
    onValueClick?: (value: BreakdownSinglePropertyStat) => void
}

export function BreakdownsStackedBar({
    properties,
    totalCount,
    propertyName,
    propertyLabel = propertyName,
    onValueClick,
}: BreakdownsStackedBarProps): JSX.Element {
    return (
        <div className="flex w-full h-4 rounded overflow-hidden bg-fill-secondary">
            {properties.map((item, index) => {
                const percentage = (item.count / totalCount) * 100
                const displayLabel = isNullBreakdown(item.label) ? BREAKDOWN_NULL_DISPLAY : item.label
                const canFilter = !!onValueClick && item.label !== BREAKDOWN_OTHER_DISPLAY
                const segmentClassName =
                    'h-full hover:opacity-80 flex items-center justify-center gap-1 min-w-0 focus-visible:z-10 focus-visible:outline focus-visible:outline-2 focus-visible:outline-primary'
                const segmentStyle = {
                    width: `${percentage}%`,
                    backgroundColor: getSeriesColor(index),
                }

                return (
                    <Tooltip
                        key={index}
                        delayMs={0}
                        title={
                            <>
                                <div className="flex items-center gap-1.5 font-semibold">
                                    <PropertyIcon property={propertyName} value={item.label} />
                                    <span>{displayLabel}</span>
                                </div>
                                <div className="opacity-70">
                                    {humanFriendlyLargeNumber(item.count)} occurrences · {percentage.toFixed(1)}%
                                </div>
                                {canFilter && <div className="opacity-70">Click to filter</div>}
                            </>
                        }
                    >
                        {canFilter ? (
                            <button
                                type="button"
                                className={segmentClassName}
                                style={segmentStyle}
                                aria-label={`Filter by ${propertyLabel}: ${displayLabel}`}
                                onClick={() => onValueClick?.(item)}
                            >
                                {percentage > 8 && (
                                    <PropertyIcon
                                        property={propertyName}
                                        value={item.label}
                                        className="text-white text-xs opacity-90"
                                    />
                                )}
                                {percentage > 24 && (
                                    <span className="truncate text-[10px] font-medium text-white">{displayLabel}</span>
                                )}
                            </button>
                        ) : (
                            <div className={segmentClassName} style={segmentStyle}>
                                {percentage > 8 && (
                                    <PropertyIcon
                                        property={propertyName}
                                        value={item.label}
                                        className="text-white text-xs opacity-90"
                                    />
                                )}
                            </div>
                        )}
                    </Tooltip>
                )
            })}
        </div>
    )
}
