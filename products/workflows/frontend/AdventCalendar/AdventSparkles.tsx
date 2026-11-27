import './AdventPictureCast.scss'

import { CSSProperties } from 'react'

import { cn } from 'lib/utils/css-classes'

import { adventDayColor } from './adventGraph'

export interface AdventSparklesProps {
    count: number
    seed: number
    shape: 'star' | 'chip'
}

export function AdventSparkles({ count, seed, shape }: AdventSparklesProps): JSX.Element {
    return (
        <span className="pointer-events-none absolute left-1/2 top-1/2 z-10" aria-hidden>
            {Array.from({ length: count }, (_, index) => {
                const angle = (index / count) * Math.PI * 2 + seed
                const distance = 110 + ((index * 37 + seed * 11) % 70)
                const size = 8 + ((index * 5 + seed) % 8)
                return (
                    <span
                        key={index}
                        className={cn('AdventSparkle', shape === 'chip' && 'AdventSparkle--chip')}
                        style={
                            {
                                '--advent-sparkle-x': `${Math.round(Math.cos(angle) * distance)}px`,
                                '--advent-sparkle-y': `${Math.round(Math.sin(angle) * distance)}px`,
                                '--advent-sparkle-size': `${size}px`,
                                '--advent-sparkle-delay': `${(index % 6) * 30}ms`,
                                '--advent-sparkle-turn': `${(index * 67) % 360}deg`,
                                '--advent-sparkle-color': adventDayColor(index + seed),
                            } as CSSProperties
                        }
                    />
                )
            })}
        </span>
    )
}
