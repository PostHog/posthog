import { useCallback, useEffect, useRef } from 'react'
import { useInView } from 'react-intersection-observer'

import { uuid } from 'lib/utils/dom'

import { MessageAudienceDestination, captureMessageAudienceShown } from './messageAudience'

export interface MessageAudienceAttempts {
    idFor: (destination: MessageAudienceDestination) => string
    shown: Set<string>
}

export function useMessageAudienceAttempts(): MessageAudienceAttempts {
    const attempts = useRef<MessageAudienceAttempts | null>(null)
    if (!attempts.current) {
        const ids = new Map<MessageAudienceDestination, string>()
        attempts.current = {
            idFor: (destination) => {
                const id = ids.get(destination) ?? uuid()
                ids.set(destination, id)
                return id
            },
            shown: new Set(),
        }
    }
    return attempts.current
}

export interface MessageAudienceSpotProps {
    attempts: MessageAudienceAttempts
    source: string
    destination: MessageAudienceDestination
    disabled?: boolean
    children: React.ReactNode
}

export function MessageAudienceSpot({
    attempts,
    source,
    destination,
    disabled = false,
    children,
}: MessageAudienceSpotProps): JSX.Element {
    const attemptId = attempts.idFor(destination)
    const current = useRef({ attempts, source, destination, attemptId, disabled })
    current.current = { attempts, source, destination, attemptId, disabled }
    const onScreen = useRef(false)

    const reportIfSeen = useCallback(() => {
        const { attempts, source, destination, attemptId, disabled } = current.current
        if (!onScreen.current || disabled || attempts.shown.has(attemptId)) {
            return
        }
        attempts.shown.add(attemptId)
        captureMessageAudienceShown(source, destination, attemptId)
    }, [])

    const { ref } = useInView({
        skip: disabled,
        onChange: (inView) => {
            onScreen.current = inView
            reportIfSeen()
        },
    })

    useEffect(() => {
        if (disabled) {
            onScreen.current = false
        }
    }, [disabled])
    useEffect(reportIfSeen, [reportIfSeen, attemptId])

    return <span ref={ref}>{children}</span>
}
