import './AdventSnowPuffs.scss'

import { CSSProperties } from 'react'

import type { AdventSnowPuff } from './adventCalendarLogic'
import { adventPictureAt } from './adventGraph'

const FLAKES = Array.from({ length: 16 }, (_, index) => {
    const angle = (index / 16) * Math.PI * 2
    const distance = 3 + ((index * 7) % 5) * 0.6
    return {
        x: `${(Math.cos(angle) * distance).toFixed(2)}cqw`,
        y: `${(Math.sin(angle) * distance).toFixed(2)}cqw`,
        size: `${0.35 + ((index * 3) % 4) * 0.12}cqw`,
        delay: `${(index % 4) * 40}ms`,
    }
})

export interface AdventSnowPuffsProps {
    puffs: AdventSnowPuff[]
    onDone: () => void
}

export function AdventSnowPuffs({ puffs, onDone }: AdventSnowPuffsProps): JSX.Element {
    return (
        <>
            {puffs.map((puff, puffIndex) => (
                <span
                    key={puff.id}
                    className="AdventSnowPuff"
                    style={adventPictureAt(puff)}
                    data-attr="advent-snow-puff"
                    aria-hidden
                >
                    <span className="AdventSnowPuff__cloud" onAnimationEnd={puffIndex === 0 ? onDone : undefined} />
                    {FLAKES.map((flake, index) => (
                        <span
                            key={index}
                            className="AdventSnowPuff__flake"
                            style={
                                {
                                    '--advent-puff-x': flake.x,
                                    '--advent-puff-y': flake.y,
                                    '--advent-puff-size': flake.size,
                                    '--advent-puff-delay': flake.delay,
                                } as CSSProperties
                            }
                        />
                    ))}
                </span>
            ))}
        </>
    )
}
