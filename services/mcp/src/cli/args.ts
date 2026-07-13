export function takeFlag(args: string[], flag: string): boolean {
    const index = args.indexOf(flag)
    if (index === -1) {
        return false
    }
    args.splice(index, 1)
    return true
}

export function takeOption(args: string[], flag: string): string | undefined {
    const index = args.indexOf(flag)
    if (index === -1) {
        return undefined
    }

    const value = args[index + 1]
    if (value === undefined || value.startsWith('--')) {
        throw new Error(`Missing value for ${flag}`)
    }

    args.splice(index, 2)
    return value
}
