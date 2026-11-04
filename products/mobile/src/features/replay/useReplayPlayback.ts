import { useRef, useState } from 'react'

import { trackFullReplayOpened } from './replayAnalytics'

export function useReplayPlayback(sessionId: string): { open: () => void; close: () => void; visible: boolean } {
    const [visible, setVisible] = useState(false)
    const inFlight = useRef(false)
    const open = (): void => {
        if (inFlight.current) return
        inFlight.current = true
        trackFullReplayOpened(sessionId)
        setVisible(true)
    }
    const close = (): void => {
        inFlight.current = false
        setVisible(false)
    }
    return { open, close, visible }
}
