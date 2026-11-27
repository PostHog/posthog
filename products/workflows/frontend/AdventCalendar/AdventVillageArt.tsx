import { ADVENT_PICTURE } from './adventGraph'
import { AdventPalette, AdventPaletteColor, adventStroke } from './adventPalette'

const { width: WIDTH, height: HEIGHT } = ADVENT_PICTURE

const BLEED = 1500
const LEFT = -BLEED
const RIGHT = WIDTH + BLEED
const BOTTOM = HEIGHT + BLEED

const SHADOW = 'url(#advent-village-shadow)'
const FAR_GROUND = 104
const STREET_GROUND = 300
const FRONT_GROUND = 500

const STARS = Array.from({ length: 110 }, (_, index) => ({
    x: ((index * 211) % 2700) - 750,
    y: ((index * 53) % 330) - 250,
    r: 1 + (index % 3) * 0.5,
}))
const PEAKS = Array.from({ length: 26 }, (_, index) => ({
    x: (index - 9) * 170 + 40,
    y: 38 + ((index * 37) % 5) * 11,
}))
const FAR_PINES = Array.from({ length: 44 }, (_, index) => ({
    x: LEFT + 60 + index * 96 + ((index * 29) % 40),
    height: 22 + ((index * 13) % 12),
}))
const HOUSES: [number, AdventPaletteColor][] = [
    [-420, 'blue'],
    [-150, 'paper'],
    [120, 'red'],
    [410, 'paper'],
    [660, 'blue'],
    [910, 'red'],
    [1160, 'paper'],
    [1440, 'blue'],
    [1720, 'red'],
]
const STREET_PINES = [-560, -290, -20, 285, 535, 785, 1035, 1300, 1580, 1850]
const FRONT_PINES = [-640, -470, -310, -150, 535, 1035, 1310, 1450, 1620, 1790]
const LAMPS = [285, 785]

function ground(y: number, swell: number, period: number): string {
    const points: string[] = []
    for (let x = LEFT; x <= RIGHT; x += 60) {
        points.push(`${x} ${(y + swell * Math.sin(x / period)).toFixed(1)}`)
    }
    return `M${points.join(' L')} V${BOTTOM} H${LEFT}Z`
}

function Pine({
    x,
    base,
    height,
    palette,
}: {
    x: number
    base: number
    height: number
    palette: AdventPalette
}): JSX.Element {
    const half = height * 0.34
    return (
        <g>
            <rect x={x - 2} y={base - height * 0.16} width={4} height={height * 0.16} fill={palette.timber} />
            <path
                d={`M${x - half} ${base - height * 0.14} L${x} ${base - height * 0.72} L${x + half} ${base - height * 0.14}Z`}
                fill={palette.pine}
            />
            <path
                d={`M${x - half * 0.72} ${base - height * 0.48} L${x} ${base - height} L${x + half * 0.72} ${base - height * 0.48}Z`}
                fill={palette.pine}
            />
            <path
                d={`M${x - half * 0.3} ${base - height * 0.8} L${x} ${base - height} L${x + half * 0.3} ${base - height * 0.8}Z`}
                fill={palette.snow}
            />
        </g>
    )
}

function House({ x, tone, palette }: { x: number; tone: AdventPaletteColor; palette: AdventPalette }): JSX.Element {
    const base = STREET_GROUND
    return (
        <g>
            <rect x={x + 14} y={base - 74} width={10} height={22} fill={palette.timber} />
            <rect x={x + 12} y={base - 77} width={14} height={5} fill={palette.snow} />
            <rect x={x - 36} y={base - 42} width={72} height={42} fill={palette[tone]} />
            <path d={`M${x - 46} ${base - 40} L${x} ${base - 74} L${x + 46} ${base - 40}Z`} fill={palette.timber} />
            <path
                d={`M${x - 46} ${base - 40} L${x} ${base - 74} L${x + 46} ${base - 40} L${x + 37} ${base - 40} L${x} ${base - 65} L${x - 37} ${base - 40}Z`}
                fill={palette.snow}
            />
            <rect x={x - 27} y={base - 31} width={14} height={15} rx={2} fill={palette.gold} />
            <rect x={x + 13} y={base - 31} width={14} height={15} rx={2} fill={palette.gold} />
            <rect x={x - 6} y={base - 24} width={12} height={24} rx={2} fill={palette.timber} />
        </g>
    )
}

function Lamp({ x, palette }: { x: number; palette: AdventPalette }): JSX.Element {
    const base = FRONT_GROUND
    return (
        <g>
            <circle cx={x} cy={base - 46} r={17} fill={palette.gold} opacity={0.22} />
            <path d={`M${x} ${base} V${base - 40}`} {...adventStroke(palette.ink, 3)} />
            <circle cx={x} cy={base - 46} r={6} fill={palette.gold} />
            <path d={`M${x - 7} ${base - 53} H${x + 7}`} {...adventStroke(palette.ink, 3)} />
        </g>
    )
}

function Snowman({ x, base, palette }: { x: number; base: number; palette: AdventPalette }): JSX.Element {
    return (
        <g>
            <circle cx={x} cy={base - 18} r={20} fill={palette.paper} />
            <circle cx={x} cy={base - 47} r={14} fill={palette.paper} />
            <circle cx={x} cy={base - 69} r={10} fill={palette.paper} />
            <path
                d={`M${x - 13} ${base - 56} H${x + 13} L${x + 16} ${base - 40} H${x + 9} L${x + 8} ${base - 51} H${x - 13}Z`}
                fill={palette.red}
            />
            <rect x={x - 12} y={base - 80} width={24} height={4} rx={2} fill={palette.ink} />
            <rect x={x - 8} y={base - 94} width={16} height={15} fill={palette.ink} />
            <path d={`M${x} ${base - 68} l12 3 l-12 2Z`} fill={palette.ember} />
            <circle cx={x - 4} cy={base - 72} r={1.5} fill={palette.ink} />
            <circle cx={x + 4} cy={base - 72} r={1.5} fill={palette.ink} />
            <circle cx={x} cy={base - 48} r={1.8} fill={palette.ink} />
            <circle cx={x} cy={base - 38} r={1.8} fill={palette.ink} />
        </g>
    )
}

function Tree({ x, base, palette }: { x: number; base: number; palette: AdventPalette }): JSX.Element {
    const top = base - 178
    return (
        <g>
            <rect x={x - 7} y={base - 18} width={14} height={18} fill={palette.timber} />
            <path d={`M${x} ${base - 112} L${x + 58} ${base - 14} H${x - 58}Z`} fill={palette.pine} />
            <path d={`M${x} ${base - 148} L${x + 45} ${base - 62} H${x - 45}Z`} fill={palette.pine} />
            <path d={`M${x} ${top} L${x + 32} ${base - 106} H${x - 32}Z`} fill={palette.pine} />
            <path
                d={`M${x - 45} ${base - 62} Q${x} ${base - 46} ${x + 45} ${base - 62}`}
                {...adventStroke(palette.gold)}
            />
            <path
                d={`M${x - 32} ${base - 106} Q${x} ${base - 92} ${x + 32} ${base - 106}`}
                {...adventStroke(palette.gold)}
            />
            <circle cx={x - 18} cy={base - 84} r={4} fill={palette.red} />
            <circle cx={x + 20} cy={base - 76} r={4} fill={palette.gold} />
            <circle cx={x - 30} cy={base - 34} r={4} fill={palette.gold} />
            <circle cx={x + 4} cy={base - 40} r={4} fill={palette.red} />
            <circle cx={x + 34} cy={base - 30} r={4} fill={palette.paper} />
            <circle cx={x - 6} cy={base - 124} r={3.5} fill={palette.paper} />
            <path
                d={`M${x} ${top - 16} l4 9 l10 1 l-7 7 l2 10 l-9 -5 l-9 5 l2 -10 l-7 -7 l10 -1Z`}
                fill={palette.gold}
            />
        </g>
    )
}

export function AdventVillageArt({ palette }: { palette: AdventPalette }): JSX.Element {
    return (
        <svg
            viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
            width="100%"
            height="100%"
            overflow="visible"
            className="absolute inset-0"
            aria-hidden
        >
            <defs>
                <filter
                    id="advent-village-shadow"
                    filterUnits="userSpaceOnUse"
                    x={LEFT}
                    y={-BLEED}
                    width={RIGHT - LEFT}
                    height={BOTTOM + BLEED}
                >
                    <feDropShadow dx={0} dy={-2} stdDeviation={2} floodColor={palette.ink} floodOpacity={0.3} />
                </filter>
                <linearGradient id="advent-village-sky" gradientUnits="userSpaceOnUse" x1={0} y1={-260} x2={0} y2={130}>
                    <stop offset={0} stopColor={palette.ink} />
                    <stop offset={0.55} stopColor={palette.night} />
                    <stop offset={1} stopColor={palette.dusk} />
                </linearGradient>
            </defs>
            <rect x={LEFT} y={-BLEED} width={RIGHT - LEFT} height={BLEED - 260} fill={palette.ink} />
            <rect x={LEFT} y={-261} width={RIGHT - LEFT} height={500} fill="url(#advent-village-sky)" />
            {STARS.map((star, index) => (
                <circle key={index} cx={star.x} cy={star.y} r={star.r} fill={palette.paper} />
            ))}
            <circle cx={1010} cy={44} r={32} fill={palette.paper} opacity={0.16} />
            <circle cx={1010} cy={44} r={19} fill={palette.paper} />
            <g filter={SHADOW}>
                <path
                    fill={palette.dusk}
                    d={`M${LEFT} 126 ${PEAKS.map((peak) => `L${peak.x - 85} 120 L${peak.x} ${peak.y}`).join(' ')} L${RIGHT} 126 V220 H${LEFT}Z`}
                />
                {PEAKS.filter((peak) => peak.y < 62).map((peak) => (
                    <path
                        key={peak.x}
                        fill={palette.snow}
                        d={`M${peak.x} ${peak.y} l15 14 l-8 -1 l-7 6 l-7 -6 l-8 1Z`}
                    />
                ))}
            </g>
            <g filter={SHADOW}>
                {FAR_PINES.map((pine) => (
                    <Pine key={pine.x} x={pine.x} base={FAR_GROUND + 4} height={pine.height} palette={palette} />
                ))}
                <path fill={palette.ice} d={ground(FAR_GROUND, 5, 150)} />
            </g>
            <g filter={SHADOW}>
                <path fill={palette.shade} d={ground(266, 6, 190)} />
                {STREET_PINES.map((x, index) => (
                    <Pine key={x} x={x} base={STREET_GROUND - 2} height={44 + (index % 3) * 6} palette={palette} />
                ))}
                {HOUSES.map(([x, tone]) => (
                    <House key={x} x={x} tone={tone} palette={palette} />
                ))}
                <Pine x={92} base={430} height={62} palette={palette} />
                <Pine x={142} base={438} height={46} palette={palette} />
            </g>
            <g filter={SHADOW}>
                <path fill={palette.snow} d={ground(478, 7, 230)} />
                {FRONT_PINES.map((x, index) => (
                    <Pine key={x} x={x} base={FRONT_GROUND + 2} height={50 + (index % 3) * 8} palette={palette} />
                ))}
                {LAMPS.map((x) => (
                    <Lamp key={x} x={x} palette={palette} />
                ))}
                <Tree x={1166} base={574} palette={palette} />
                <Snowman x={118} base={618} palette={palette} />
            </g>
        </svg>
    )
}
