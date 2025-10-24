import { useState } from 'react'

import { getSeriesColor } from 'lib/colors'
import { PropertyIcon } from 'lib/components/PropertyIcon/PropertyIcon'

import { BreakdownSinglePropertyStat } from './breakdownPreviewLogic'

interface BreakdownStackedBarProps {
    properties: BreakdownSinglePropertyStat[]
    totalCount: number
    propertyName: string
}

export function BreakdownStackedBar({ properties, totalCount, propertyName }: BreakdownStackedBarProps): JSX.Element {
    const [hoveredIndex, setHoveredIndex] = useState<number | null>(null)
    const [tooltipPosition, setTooltipPosition] = useState({ x: 0, y: 0 })

    const handleMouseEnter = (index: number, event: React.MouseEvent<HTMLDivElement>): void => {
        setHoveredIndex(index)
        const rect = event.currentTarget.getBoundingClientRect()
        setTooltipPosition({
            x: rect.left + rect.width / 2,
            y: rect.top,
        })
    }

    return (
        <div className="relative">
            {/* Bar itself */}
            <div className="flex w-full h-4 rounded overflow-hidden bg-fill-secondary">
                {properties.map((item, index) => {
                    const percentage = (item.count / totalCount) * 100

                    return (
                        <div
                            key={index}
                            className="h-full transition-all hover:opacity-80 cursor-pointer flex items-center justify-center"
                            style={{
                                width: `${percentage}%`,
                                backgroundColor: getSeriesColor(index),
                            }}
                            onMouseEnter={(e) => handleMouseEnter(index, e)}
                            onMouseLeave={() => setHoveredIndex(null)}
                        >
                            {percentage > 8 && (
                                <PropertyIcon
                                    property={propertyName}
                                    value={item.label}
                                    className="text-white text-xs opacity-90"
                                />
                            )}
                        </div>
                    )
                })}
            </div>
            {/* Tooltip */}
            {hoveredIndex !== null && (
                <div
                    className="fixed px-2 py-1 bg-bg-3000 border border-border rounded shadow-lg whitespace-nowrap z-[9999] text-xs pointer-events-none"
                    style={{
                        left: `${tooltipPosition.x}px`,
                        top: `${tooltipPosition.y - 8}px`,
                        transform: 'translate(-50%, -100%)',
                    }}
                >
                    <div className="flex items-center gap-1.5 font-semibold">
                        <PropertyIcon property={propertyName} value={properties[hoveredIndex].label} />
                        <span>{properties[hoveredIndex].label}</span>
                    </div>
                    <div className="text-muted">
                        {((properties[hoveredIndex].count / totalCount) * 100).toFixed(1)}%
                    </div>
                </div>
            )}
        </div>
    )
}
