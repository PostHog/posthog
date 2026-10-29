import { type ReactElement, useId } from 'react'
import { Defs, LinearGradient, Path, Stop } from 'react-native-svg'

import { useColors } from '../theme'

export type LogomarkPart = 'blue' | 'red' | 'yellow' | 'head'

interface Facet {
    x1: number
    x2: number
    y: number
    from: string
    to: string
    toOffset?: number
    d: string
}

/** The nine gradient facets of the @posthog/brand logomark, in paint order. Each gradient runs horizontally along `y`. */
const FACETS: readonly Facet[] = [
    {
        x1: 21.96,
        x2: 33.28,
        y: 9.62,
        from: '#ffd849',
        to: '#fbae01',
        toOffset: 0.96,
        d: 'M21.96 2.67v4.96l11.3 11.6h.02V7.75L26.63.85a2.8 2.8 0 0 0-2-.85 2.67 2.67 0 0 0-2.67 2.67',
    },
    { x1: 21.96, x2: 33.28, y: 17.81, from: '#ffb700', to: '#f9aa01', d: 'M21.96 7.63v11.05L31.03 28h2.25v-8.75z' },
    { x1: 21.96, x2: 31.03, y: 23.34, from: '#ff9500', to: '#f8aa00', d: 'M21.96 28h9.07l-9.07-9.32z' },
    {
        x1: 10.74,
        x2: 21.96,
        y: 9.34,
        from: '#ff651e',
        to: '#e4400a',
        d: 'M10.74 2.66v4.5l11.22 11.52V7.63L15.3.8a2.66 2.66 0 0 0-4.56 1.86',
    },
    { x1: 10.74, x2: 19.7, y: 23.34, from: '#c42c00', to: '#d63600', d: 'M10.74 28h8.96l-8.96-9.32z' },
    { x1: 10.74, x2: 21.96, y: 17.58, from: '#ef3c00', to: '#d63601', d: 'M10.74 7.16v11.52L19.7 28h2.26v-9.32z' },
    {
        x1: 0,
        x2: 10.74,
        y: 9.34,
        from: '#3f80ff',
        to: '#084fe0',
        d: 'M10.74 7.16 4.54.8A2.66 2.66 0 0 0 0 2.66V7.5l10.74 11.18z',
    },
    { x1: 0, x2: 10.74, y: 17.75, from: '#0255ff', to: '#0145d2', d: 'M9.19 28h1.55v-9.32L0 7.5v10.73z' },
    { x1: 0, x2: 9.19, y: 23.11, from: '#0041c6', to: '#0045d0', d: 'M0 25.41A2.6 2.6 0 0 0 2.58 28H9.2L0 18.23z' },
]

const HEAD_PATH =
    'M51.66 25.22A1.9 1.9 0 0 0 50 23.33l-.34-.04c-1-.13-1.94-.6-2.65-1.33L33.28 7.75V28H49a2.66 2.66 0 0 0 2.67-2.67zM39.2 23.54h-.09a1.78 1.78 0 1 1 .1 0'

/** The gradient hedgehog from @posthog/brand, drawn in a 52 x 28 viewBox. */
export function LogomarkShapes({ part }: { part?: LogomarkPart }): ReactElement {
    // The head follows the text color, so it stays visible on a dark background.
    const { ink } = useColors()
    // useId wraps its value in punctuation that is not safe inside a url(#...) reference.
    const prefix = useId().replace(/[^A-Za-z0-9]/g, '')
    const facets = FACETS.filter((_, index) => !part || (index < 3 ? 'yellow' : index < 6 ? 'red' : 'blue') === part)
    return (
        <>
            <Defs>
                {facets.map((facet, index) => (
                    <LinearGradient
                        key={facet.d}
                        id={`${prefix}${index}`}
                        x1={facet.x1}
                        y1={facet.y}
                        x2={facet.x2}
                        y2={facet.y}
                        gradientUnits="userSpaceOnUse"
                    >
                        <Stop offset={0} stopColor={facet.from} />
                        <Stop offset={facet.toOffset ?? 1} stopColor={facet.to} />
                    </LinearGradient>
                ))}
            </Defs>
            {(!part || part === 'head') && <Path fill={ink} d={HEAD_PATH} />}
            {facets.map((facet, index) => (
                <Path key={facet.d} fill={`url(#${prefix}${index})`} d={facet.d} />
            ))}
        </>
    )
}
