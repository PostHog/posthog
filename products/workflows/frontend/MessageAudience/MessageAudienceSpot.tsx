import { useCallback, useEffect, useRef } from 'react'
import { useInView } from 'react-intersection-observer'

import { uuid } from 'lib/utils/dom'

import { MessageAudienceDestination, captureMessageAudienceShown, holdMessageAudienceAttempt } from './messageAudience'

export interface MessageAudienceSpotProps {
    source: string
    destination: MessageAudienceDestination
    disabled?: boolean
    children: React.ReactNode
}

export function MessageAudienceSpot({
    source,
    destination,
    disabled = false,
    children,
}: MessageAudienceSpotProps): JSX.Element {
    const attemptIds = useRef<Record<string, string>>({})
    const key = `${source}:${destination}`
    attemptIds.current[key] ??= uuid()
    const attemptId = attemptIds.current[key]

    const current = useRef({ source, destination, attemptId, disabled })
    current.current = { source, destination, attemptId, disabled }
    const onScreen = useRef(false)
    const reported = useRef(new Set<string>())
    const holds = useRef(new Map<string, () => void>())

    const reportIfSeen = useCallback(() => {
        const { source, destination, attemptId, disabled } = current.current
        if (!onScreen.current || disabled) {
            return
        }
        if (!holds.current.has(attemptId)) {
            holds.current.set(attemptId, holdMessageAudienceAttempt(source, destination, attemptId))
        }
        if (!reported.current.has(attemptId)) {
            reported.current.add(attemptId)
            captureMessageAudienceShown(source, destination, attemptId)
        }
    }, [])

    const { ref } = useInView({
        onChange: (inView) => {
            onScreen.current = inView
            reportIfSeen()
        },
    })

    useEffect(reportIfSeen, [reportIfSeen, disabled, attemptId])

    useEffect(
        () => () => {
            holds.current.get(attemptId)?.()
            holds.current.delete(attemptId)
        },
        [attemptId]
    )

    return <span ref={ref}>{children}</span>
}
