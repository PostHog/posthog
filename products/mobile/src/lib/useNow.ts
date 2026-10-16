import { useEffect, useState } from 'react'

export function useNow(intervalMs: number = 30_000): Date {
    const [now, setNow] = useState(() => new Date())
    useEffect(() => {
        const timer = setInterval(() => setNow(new Date()), intervalMs)
        return () => clearInterval(timer)
    }, [intervalMs])
    return now
}
