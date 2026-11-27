import { ADVENT_LAST_DAY } from '../adventContent'
import { AdventRewards } from '../adventDraw'
import { AdventDoor, AdventDoorStatus, AdventProgress, buildAdventGraph } from '../adventGraph'

const STATUS_PRECEDENCE: AdventDoorStatus[] = ['locked', 'ready', 'open']

export function adventEntryDoors(progress: AdventProgress, rewards: AdventRewards, today: number): AdventDoor[] {
    const byDay = new Map<number, AdventDoor>()
    for (const door of buildAdventGraph(progress, today, rewards).doors) {
        const kept = byDay.get(door.day)
        if (!kept || STATUS_PRECEDENCE.indexOf(door.status) > STATUS_PRECEDENCE.indexOf(kept.status)) {
            byDay.set(door.day, door)
        }
    }
    return Array.from({ length: ADVENT_LAST_DAY }, (_, index) => byDay.get(index + 1)).filter(
        (door): door is AdventDoor => !!door
    )
}
