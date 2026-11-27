import { useEffect, useState } from 'react'
import { useInView } from 'react-intersection-observer'

import { uuid } from 'lib/utils/dom'

import { MessageAudienceDestination, captureMessageAudienceShown, holdMessageAudienceAttempt } from './messageAudience'

export interface MessageAudienceSpotProps {
    source: string
    destination: MessageAudienceDestination
    children: React.ReactNode
}

export function MessageAudienceSpot({ source, destination, children }: MessageAudienceSpotProps): JSX.Element {
    const [attemptId] = useState(uuid)
    const { ref, inView } = useInView({ triggerOnce: true })

    useEffect(() => holdMessageAudienceAttempt(source, destination, attemptId), [source, destination, attemptId])

    useEffect(() => {
        if (inView) {
            captureMessageAudienceShown(source, destination, attemptId)
        }
    }, [inView, source, destination, attemptId])

    return <span ref={ref}>{children}</span>
}
