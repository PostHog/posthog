import { useEffect, useState } from 'react'

export function useNow(intervalMs: number | null = 30_000): Date {
    const [now, setNow] = useState(() => new Date())
    useEffect(() => {
        if (intervalMs === null) return
        setNow(new Date())
        const timer = setInterval(() => setNow(new Date()), intervalMs)
        return () => clearInterval(timer)
    }, [intervalMs])
    return now
}
