import { ReactNode, useLayoutEffect, useRef } from 'react'

import { ExperimentRefreshReady, isExperimentRefreshCommitted } from './experimentRefreshJourney'

export function ExperimentRefreshResultsBoundary({
    children,
    ready,
    primary,
    secondary,
    exposures,
    blocked,
    observe,
    committed,
}: {
    children: ReactNode
    ready: ExperimentRefreshReady | null
    primary: readonly unknown[]
    secondary: readonly unknown[]
    exposures: unknown
    blocked: boolean
    observe: (observed: boolean) => void
    committed: (id: string) => void
}): JSX.Element {
    const lastCommitted = useRef<string>()
    useLayoutEffect(() => {
        observe(true)
        return () => observe(false)
    }, [observe])
    useLayoutEffect(() => {
        if (
            !blocked &&
            ready &&
            lastCommitted.current !== ready.attemptId &&
            isExperimentRefreshCommitted(ready, primary, secondary, exposures)
        ) {
            lastCommitted.current = ready.attemptId
            committed(ready.attemptId)
        }
    }, [ready, primary, secondary, exposures, blocked, committed])
    return <>{children}</>
}
