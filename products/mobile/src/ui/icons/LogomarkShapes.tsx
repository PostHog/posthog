import { type ReactElement, useId } from 'react'
import { Defs, LinearGradient, Path, Stop } from 'react-native-svg'

import { useTheme } from '../theme'

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

const WHITE_PATHS: Record<LogomarkPart, string> = {
    blue: 'M.87 19.13a.5.5 0 0 0-.87.34v5.94a2.6 2.6 0 0 0 2.59 2.58H7.8a.5.5 0 0 0 .37-.84zM.86 8.4c-.3-.32-.86-.1-.86.36v6.73q0 .2.13.34l8.81 9.68 1.8 2.06v-8.82zM4.59.82A2.67 2.67 0 0 0 0 2.68v1.93q0 .4.27.69l10.47 10.95v-9.1z',
    red: 'M11.36 28h7.08a.5.5 0 0 0 .36-.85l-8.05-8.4v8.8l.23.28q.16.17.38.17m-.61-11.76 8.84 9.25 2.1 2.33q.1.11.27.14V18.7L10.75 7.15zm0-13.7v1.41a2 2 0 0 0 .55 1.28L21.96 16.2V7.65L15.32.8a2.67 2.67 0 0 0-4.57 1.71z',
    yellow: 'M22.06 28h7.76a.5.5 0 0 0 .36-.86l-8.22-8.45v9.27l.09.02zM31 25.49l1.13 1.14c.32.31.85.09.85-.35v-7.3l-.49-.51L21.96 7.64v8.55zM22.52 5.73l9.62 9.89c.3.32.86.1.86-.35V7.46L26.56.82a2.67 2.67 0 0 0-4.59 1.84v1.7c0 .51.2 1 .57 1.37z',
    head: 'm50 23.34-.35-.05A4.5 4.5 0 0 1 47 21.97L35.56 10.1c-.3-.33-.86-.1-.86.35V27.5c0 .27.22.5.5.5h13.78c1.48 0 2.67-1.2 2.67-2.67v-.1a1.9 1.9 0 0 0-1.67-1.89zm-10.81.2a1.8 1.8 0 1 1 0-3.58 1.8 1.8 0 0 1 0 3.58',
}

/** The hedgehog from @posthog/brand, drawn in a 52 x 28 viewBox. */
export function LogomarkShapes({ part }: { part?: LogomarkPart }): ReactElement {
    const { scheme, colors } = useTheme()
    // useId wraps its value in punctuation that is not safe inside a url(#...) reference.
    const prefix = useId().replace(/[^A-Za-z0-9]/g, '')
    if (scheme === 'dark') {
        return <Path fill={colors.white} d={part ? WHITE_PATHS[part] : Object.values(WHITE_PATHS).join(' ')} />
    }

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
            {(!part || part === 'head') && <Path fill={colors.ink} d={HEAD_PATH} />}
            {facets.map((facet, index) => (
                <Path key={facet.d} fill={`url(#${prefix}${index})`} d={facet.d} />
            ))}
        </>
    )
}
