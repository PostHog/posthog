import { getSeriesColor } from 'lib/colors'
import { PropertyIcon } from 'lib/components/PropertyIcon/PropertyIcon'
import { Tooltip } from 'lib/lemon-ui/Tooltip'

import { BreakdownSinglePropertyStat } from './miniBreakdownsLogic'

interface BreakdownsStackedBarProps {
    properties: BreakdownSinglePropertyStat[]
    totalCount: number
    propertyName: string
}

export function BreakdownsStackedBar({ properties, totalCount, propertyName }: BreakdownsStackedBarProps): JSX.Element {
    return (
        <div className="flex w-full h-4 rounded overflow-hidden bg-fill-secondary">
            {properties.map((item, index) => {
                const percentage = (item.count / totalCount) * 100

                return (
                    <Tooltip
                        key={index}
                        delayMs={0}
                        title={
                            <>
                                <div className="flex items-center gap-1.5 font-semibold">
                                    <PropertyIcon property={propertyName} value={item.label} />
                                    <span>{item.label}</span>
                                </div>
                                <div className="opacity-70">{percentage.toFixed(1)}%</div>
                            </>
                        }
                    >
                        <div
                            className="h-full hover:opacity-80 flex items-center justify-center"
                            style={{
                                width: `${percentage}%`,
                                backgroundColor: getSeriesColor(index),
                            }}
                        >
                            {percentage > 8 && (
                                <PropertyIcon
                                    property={propertyName}
                                    value={item.label}
                                    className="text-white text-xs opacity-90"
                                />
                            )}
                        </div>
                    </Tooltip>
                )
            })}
        </div>
    )
}
