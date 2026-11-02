import { useValues } from 'kea'

import { sessionRecordingPlayerLogic } from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'

import { visionSurfaceShown } from '../utils/visionSurface'
import { RecordingMoments } from './RecordingMoments'

export function PlayerSidebarObservationsTab(): JSX.Element | null {
    const { sessionRecordingId, logicProps } = useValues(sessionRecordingPlayerLogic)

    // ?tab=observations and the singleton sidebar logic can activate this tab in players whose sidebar never offered it
    if (!visionSurfaceShown(logicProps) || !sessionRecordingId) {
        return null
    }
    return <RecordingMoments key={sessionRecordingId} sessionId={sessionRecordingId} playerLogicProps={logicProps} />
}
