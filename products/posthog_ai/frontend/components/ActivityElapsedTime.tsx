import { useEffect, useState } from 'react'

import { usePageVisibility } from 'lib/hooks/usePageVisibility'

export function ActivityElapsedTime({
    startedAt,
    endedAt,
    active,
}: {
    startedAt?: number
    endedAt?: number
    active: boolean
}): JSX.Element | null {
    const [now, setNow] = useState(Date.now)
    const { isVisible } = usePageVisibility()
    useEffect(() => {
        if (!active || startedAt === undefined || !isVisible) {
            return
        }
        setNow(Date.now())
        const interval = setInterval(() => setNow(Date.now()), 1000)
        return () => clearInterval(interval)
    }, [active, startedAt, isVisible])
    const end = active ? now : endedAt
    if (startedAt === undefined || end === undefined || end < startedAt) {
        return null
    }
    const seconds = Math.floor((end - startedAt) / 1000)
    return (
        <span
            className="tabular-nums text-muted"
            title="Elapsed time for this activity group, including tools and waiting, not the whole response."
        >
            · {seconds < 60 ? `${seconds}s` : `${Math.floor(seconds / 60)}m ${String(seconds % 60).padStart(2, '0')}s`}
        </span>
    )
}
