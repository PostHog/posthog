import { calendarDaysBetween, formatMonthDay, fullWeekdayName } from '@/lib/dates'
import type { ChatGroup, ChatListItem } from '@/model/types'

/** Labels follow the device's local calendar days. A time in the future counts as now. */
export function dayLabel(iso: string, now: Date): string {
    const parsed = new Date(iso)
    if (Number.isNaN(parsed.getTime())) {
        return 'Earlier'
    }
    const date = parsed > now ? now : parsed
    const days = calendarDaysBetween(date, now)
    if (days === 0) {
        return 'Today'
    }
    if (days === 1) {
        return 'Yesterday'
    }
    if (days < 7) {
        return fullWeekdayName(date)
    }
    const monthDay = formatMonthDay(date)
    return date.getFullYear() === now.getFullYear() ? monthDay : `${monthDay}, ${date.getFullYear()}`
}

export function groupChats(items: ChatListItem[], now: Date): ChatGroup[] {
    const groups: ChatGroup[] = []
    const byLabel = new Map<string, ChatGroup>()
    for (const item of items) {
        const label = dayLabel(item.updatedAt, now)
        let group = byLabel.get(label)
        if (!group) {
            group = { label, items: [] }
            byLabel.set(label, group)
            groups.push(group)
        }
        group.items.push(item)
    }
    return groups
}

export function filterChats(items: ChatListItem[], query: string): ChatListItem[] {
    const needle = query.trim().toLowerCase()
    if (!needle) {
        return items
    }
    return items.filter((item) => item.title.toLowerCase().includes(needle))
}
