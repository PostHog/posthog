import {
    SessionRecordingPlayerLogicProps,
    SessionRecordingPlayerMode,
} from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'

/** Single gate for every vision surface on a player (observations tab, seekbar marks): keeps embedded, shared, and chromeless players from fetching observations. */
export function visionSurfaceShown(logicProps: SessionRecordingPlayerLogicProps): boolean {
    return (
        (logicProps.mode ?? SessionRecordingPlayerMode.Standard) === SessionRecordingPlayerMode.Standard &&
        !logicProps.noMeta &&
        !logicProps.noDock
    )
}
