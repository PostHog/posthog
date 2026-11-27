import type { AdventReward } from './adventContent'
import jamesSrc from './images/james.png'
import timSrc from './images/tim.png'

export const ADVENT_FOUNDERS: Record<'james' | 'tim', AdventReward> = {
    james: {
        id: 'james',
        name: 'James Hawkins',
        image: { src: jamesSrc, aspectRatio: 399 / 400 },
        isPortrait: true,
    },
    tim: {
        id: 'tim',
        name: 'Tim Glaser',
        image: { src: timSrc, aspectRatio: 356 / 400 },
        isPortrait: true,
    },
}
