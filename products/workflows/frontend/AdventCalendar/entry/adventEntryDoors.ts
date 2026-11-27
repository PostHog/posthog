import { ADVENT_LAST_DAY } from '../adventContent'
import { AdventRewards } from '../adventDraw'
import { AdventDoor, AdventProgress, buildAdventGraph } from '../adventGraph'

export function adventEntryDoors(progress: AdventProgress, rewards: AdventRewards, today: number): AdventDoor[] {
    const byDay = new Map<number, AdventDoor>()
    for (const door of buildAdventGraph(progress, today, rewards).doors) {
        const kept = byDay.get(door.day)
        if (!kept || (kept.status !== 'open' && door.status === 'open')) {
            byDay.set(door.day, door)
        }
    }
    return Array.from({ length: ADVENT_LAST_DAY }, (_, index) => byDay.get(index + 1)).filter(
        (door): door is AdventDoor => !!door
    )
}
