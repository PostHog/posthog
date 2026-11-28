import './AdventSnow.scss'

import { CSSProperties, memo } from 'react'

const FLAKES = Array.from({ length: 42 }, (_, index) => ({
    left: `${(index * 37) % 100}%`,
    top: `${(index * 53) % 100}%`,
    size: 4 + ((index * 7) % 5),
    duration: `${10 + ((index * 13) % 9)}s`,
    delay: `-${(index * 5) % 17}s`,
    drift: (index * 11) % 7,
}))

export const AdventSnow = memo(function AdventSnow(): JSX.Element {
    return (
        <div className="AdventSnow pointer-events-none absolute inset-0 z-[4] overflow-hidden" aria-hidden>
            {FLAKES.map((flake, index) => (
                <span
                    key={index}
                    className={`AdventSnow__flake AdventSnow__flake--drift-${flake.drift} absolute`}
                    style={
                        {
                            left: flake.left,
                            width: flake.size,
                            animationDuration: flake.duration,
                            animationDelay: flake.delay,
                            '--advent-snow-rest': flake.top,
                        } as CSSProperties
                    }
                />
            ))}
        </div>
    )
})
