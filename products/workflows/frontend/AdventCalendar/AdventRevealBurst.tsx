import { cn } from 'lib/utils/css-classes'

import { adventDayColor, AdventDoor } from './adventGraph'
import { AdventRewardArt } from './AdventRewardArt'
import { AdventSparkles } from './AdventSparkles'
import type { AdventRevealPhase } from './useAdventReveal'

export function AdventRevealBurst({ door, phase }: { door: AdventDoor; phase: AdventRevealPhase }): JSX.Element {
    const color = adventDayColor(door.day)
    const isOut = phase !== 'suspense'

    return (
        <span className="relative block size-52">
            {isOut && (
                <span className="AdventReveal__pop absolute inset-0 flex items-center justify-center">
                    <span data-advent-reveal-art className="inline-flex size-44">
                        {door.reward && <AdventRewardArt reward={door.reward} className="size-full" isTitled />}
                    </span>
                </span>
            )}
            <span
                className={cn(
                    'absolute inset-0 flex items-center justify-center rounded-3xl border-4 bg-surface-primary text-7xl font-bold shadow-lg',
                    isOut ? 'AdventReveal__lid--off' : 'AdventReveal__lid--shaking'
                )}
                style={{ borderColor: color, color }}
            >
                {door.day}
            </span>
            {isOut && <AdventSparkles count={28} seed={door.day} shape="chip" />}
        </span>
    )
}
