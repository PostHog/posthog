import { humanFriendlyLargeNumber } from 'lib/utils/numbers'

export function eventsDeletedSentence(eventsDeleted: number): string {
    return `This would delete about ${humanFriendlyLargeNumber(eventsDeleted)} ${eventsDeleted === 1 ? 'event' : 'events'}.`
}
