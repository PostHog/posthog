import './AdventSnow.scss'

import { CSSProperties } from 'react'

const FLAKES = Array.from({ length: 42 }, (_, index) => ({
    left: `${(index * 37) % 100}%`,
    top: `${(index * 53) % 100}%`,
    size: 4 + ((index * 7) % 5),
    duration: `${10 + ((index * 13) % 9)}s`,
    delay: `-${(index * 5) % 17}s`,
    drift: `${(((index * 11) % 7) - 3) * 8}px`,
}))

export function AdventSnow(): JSX.Element {
    return (
        <div className="AdventSnow pointer-events-none absolute inset-0 z-[4] overflow-hidden" aria-hidden>
            {FLAKES.map((flake, index) => (
                <span
                    key={index}
                    className="AdventSnow__flake absolute rounded-full bg-white opacity-90"
                    style={
                        {
                            left: flake.left,
                            width: flake.size,
                            height: flake.size,
                            '--advent-snow-rest': flake.top,
                            '--advent-snow-duration': flake.duration,
                            '--advent-snow-delay': flake.delay,
                            '--advent-snow-drift': flake.drift,
                        } as CSSProperties
                    }
                />
            ))}
        </div>
    )
}
