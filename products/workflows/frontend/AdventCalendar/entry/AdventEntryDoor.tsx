import { cn } from 'lib/utils/css-classes'

import { AdventDoor } from '../adventGraph'

export function AdventEntryDoor({
    day,
    door,
    isToday,
}: {
    day: number
    door: AdventDoor | null
    isToday: boolean
}): JSX.Element {
    const reward = door?.status === 'open' ? door.reward : null
    return (
        <span
            className={cn(
                'AdventEntryCard__door',
                `AdventEntryCard__door--${door?.status ?? 'locked'}`,
                isToday && 'AdventEntryCard__door--today'
            )}
        >
            {reward ? (
                <img
                    src={reward.image.src}
                    alt=""
                    loading="lazy"
                    decoding="async"
                    className="size-full object-contain"
                />
            ) : (
                day
            )}
        </span>
    )
}
