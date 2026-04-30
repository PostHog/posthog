const HIGH_CHANGE_THRESHOLD = 5

export function formatDiffPercentage(value: number): string {
    if (value === 0) {
        return '0%'
    }
    if (value < 1) {
        return `${value.toFixed(1)}%`
    }
    return `${Math.round(value)}%`
}

export function DiffPercentage({
    value,
    suffix = ' change',
    className,
}: {
    value: number | null | undefined
    suffix?: string
    className?: string
}): JSX.Element | null {
    if (value == null || value <= 0) {
        return null
    }
    const isHigh = value > HIGH_CHANGE_THRESHOLD
    const classes = ['font-mono', 'tabular-nums']
    if (isHigh) {
        classes.push('text-warning-dark', 'font-semibold')
    }
    if (className) {
        classes.push(className)
    }
    return (
        <span className={classes.join(' ')}>
            {formatDiffPercentage(value)}
            {suffix}
        </span>
    )
}
