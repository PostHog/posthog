import { ADVENT_LAST_DAY } from '../adventContent'
import { AdventDoor } from '../adventGraph'
import { AdventEntryPhase } from './adventEntryPhase'

export function adventEntrySummary(doors: AdventDoor[] | null, phase: AdventEntryPhase): string | null {
    if (!doors) {
        return null
    }
    const opened = doors.filter((door) => door.status === 'open')
    const hedgehogs = opened.flatMap((door) => (door.reward ? [door.reward.name] : []))
    return [
        `You opened ${opened.length} of ${ADVENT_LAST_DAY} doors.`,
        hedgehogs.length ? `Your hedgehogs: ${hedgehogs.join(', ')}.` : null,
        phase.status === 'open' ? `Today is door ${phase.day}.` : null,
    ]
        .filter(Boolean)
        .join(' ')
}
