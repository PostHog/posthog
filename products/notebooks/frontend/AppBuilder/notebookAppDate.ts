export function isAbsoluteAppDate(value: string): boolean {
    const match =
        /^(\d{4})-(\d{2})-(\d{2})(?:[T ](?:[01]\d|2[0-3])(?::?[0-5]\d(?::?[0-5]\d(?:[.,]\d+)?)?)?(?:Z|[+-](?:[01]\d|2[0-3])(?::?[0-5]\d)?)?)?$/.exec(
            value.trim()
        )
    if (!match) {
        return false
    }
    const [, year, month, day] = match
    const calendar = new Date(0)
    calendar.setUTCFullYear(Number(year), Number(month) - 1, Number(day))
    return Number(year) > 0 && calendar.getUTCMonth() === Number(month) - 1 && calendar.getUTCDate() === Number(day)
}
