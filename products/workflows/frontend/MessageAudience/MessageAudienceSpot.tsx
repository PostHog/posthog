import { useEffect, useMemo, useRef } from 'react'
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
    const attemptId = useMemo(() => uuid(), [source, destination])
    const reported = useRef<string | null>(null)
    const { ref, inView } = useInView()

    useEffect(
        () => (disabled ? undefined : holdMessageAudienceAttempt(source, destination, attemptId)),
        [disabled, source, destination, attemptId]
    )

    useEffect(() => {
        if (inView && !disabled && reported.current !== attemptId) {
            reported.current = attemptId
            captureMessageAudienceShown(source, destination, attemptId)
        }
    }, [inView, disabled, source, destination, attemptId])

    return <span ref={ref}>{children}</span>
}
