const calendarDate = /^(\d{4})(-?)(\d{2})\2(\d{2})$/
const weekDate = /^(\d{4})(-?)W(\d{2})(?:\2([1-7]))?$/
const dateAndTime = /^(\d{4}(?:-W\d{2}(?:-[1-7])?|W\d{2}[1-7]?|-\d{2}-\d{2}|\d{4}))(?:[\s\S]([\s\S]+))?$/u
const clock = /^(\d{2})(?:(:?)(\d{2})(?:\2(\d{2})(?:[.,](\d+))?)?)?$/

function utcDate(year: number, month: number, day: number): Date {
    const date = new Date(0)
    date.setUTCFullYear(year, month - 1, day)
    return date
}

function parseDate(value: string): Date | null {
    const calendar = calendarDate.exec(value)
    if (calendar) {
        const [, year, , month, day] = calendar
        const date = utcDate(Number(year), Number(month), Number(day))
        return Number(year) > 0 && date.getUTCMonth() === Number(month) - 1 && date.getUTCDate() === Number(day)
            ? date
            : null
    }
    const match = weekDate.exec(value)
    if (!match) {
        return null
    }
    const [, year, , week, weekday = '1'] = match
    const monday = utcDate(Number(year), 1, 4)
    monday.setUTCDate(5 - (monday.getUTCDay() || 7) + (Number(week) - 1) * 7)
    const thursday = utcDate(monday.getUTCFullYear(), monday.getUTCMonth() + 1, monday.getUTCDate() + 3)
    monday.setUTCDate(monday.getUTCDate() + Number(weekday) - 1)
    return Number(year) > 0 &&
        thursday.getUTCFullYear() === Number(year) &&
        monday.getUTCFullYear() > 0 &&
        monday.getUTCFullYear() <= 9999
        ? monday
        : null
}

function validClock(value: string, offset: boolean, allowMidnightRollover = false): boolean {
    const match = clock.exec(value)
    if (!match) {
        return false
    }
    const [, hour, , minute = '0', second = '0', fraction = '0'] = match
    if (allowMidnightRollover && hour === '24') {
        return Number(minute) === 0 && Number(second) === 0 && Number(fraction.slice(0, 6)) === 0
    }
    return offset
        ? Number(hour) * 3600 + Number(minute) * 60 + Number(second) < 86400
        : Number(hour) < 24 && Number(minute) < 60 && Number(second) < 60
}

export function isAbsoluteAppDate(value: string): boolean {
    const parts = dateAndTime.exec(value.trim())
    const date = parts && parseDate(parts[1])
    if (!parts || !date) {
        return false
    }
    if (!parts[2]) {
        return true
    }
    const time = /^([^Z+-]+)(?:Z|[+-](.+))?$/.exec(parts[2])
    return !!time && validClock(time[1], false, date < utcDate(9999, 12, 31)) && (!time[2] || validClock(time[2], true))
}
