const BULBS = [
    { x: 19, y: 6, tone: 'destructive' },
    { x: 57, y: 6, tone: 'warning' },
    { x: 95, y: 6, tone: 'success' },
    { x: 133, y: 6, tone: 'completed' },
] as const

export function TodaySeasonalLights(): JSX.Element {
    return (
        <svg className="TodaySeasonalLights" aria-hidden="true">
            <defs>
                <pattern id="today-seasonal-lights" width="152" height="24" patternUnits="userSpaceOnUse">
                    <path className="TodaySeasonalLights__wire" d="M0 1 Q38 17 76 1 Q114 17 152 1" />
                    {BULBS.map(({ x, y, tone }) => (
                        <g key={x} className={`TodaySeasonalLights__bulb TodaySeasonalLights__bulb--${tone}`}>
                            <rect
                                className="TodaySeasonalLights__cap"
                                x={x - 1.8}
                                y={y - 1}
                                width="3.6"
                                height="3"
                                rx="0.8"
                            />
                            <ellipse cx={x} cy={y + 5.6} rx="2.8" ry="4.2" />
                        </g>
                    ))}
                </pattern>
            </defs>
            <rect width="100%" height="24" fill="url(#today-seasonal-lights)" />
        </svg>
    )
}
