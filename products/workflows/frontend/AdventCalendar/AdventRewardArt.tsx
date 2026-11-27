import { cn } from 'lib/utils/css-classes'

import type { AdventReward } from './adventContent'

export interface AdventRewardArtProps {
    reward: AdventReward
    className?: string
    isTitled?: boolean
}

export function AdventRewardArt({ reward, className, isTitled }: AdventRewardArtProps): JSX.Element {
    return (
        <span
            className={cn(
                'inline-flex items-center justify-center',
                reward.isPortrait && 'rounded border-4 border-warning bg-surface-primary p-[6%]',
                className
            )}
        >
            <img
                src={reward.image.src}
                alt={isTitled ? reward.name : ''}
                className="size-full object-contain"
                decoding="async"
                draggable={false}
            />
        </span>
    )
}
