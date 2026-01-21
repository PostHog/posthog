import { useActions } from 'kea'

import { Link } from 'lib/lemon-ui/Link'
import { IconPlayCircle } from 'lib/lemon-ui/icons'
import { sessionPlayerModalLogic } from 'scenes/session-recordings/player/modal/sessionPlayerModalLogic'

export interface SessionIdDisplayProps {
    sessionId: string
}

export function SessionIdDisplay({ sessionId }: SessionIdDisplayProps): JSX.Element {
    const { openSessionPlayer } = useActions(sessionPlayerModalLogic)

    return (
        <Link
            onClick={(e) => {
                e.stopPropagation()
                e.preventDefault()
                openSessionPlayer({ id: sessionId })
            }}
            className="flex items-center gap-1"
        >
            <IconPlayCircle className="text-muted" />
            <span>{sessionId}</span>
        </Link>
    )
}
