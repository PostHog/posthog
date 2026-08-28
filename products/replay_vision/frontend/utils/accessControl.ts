import { getAccessControlDisabledReason } from 'lib/utils/accessControlUtils'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

/**
 * Every Replay Vision write that creates, configures, or triggers processing of scanner/observation/
 * label/vision-action data requires BOTH replay_scanner editor access (the resource RBAC is actually
 * configured against — see RESOURCE_INHERITANCE_MAP) AND session_recording viewer access (since the
 * write exposes or processes recording-derived content). The backend enforces both unconditionally for
 * these actions (see `_scanner_for_url`/`initial()`'s `_CONFIG_ACTIONS` across scanners.py,
 * observations.py, prompt_suggestions.py, and vision_actions.py) — this must match exactly, or a
 * disabled-looking control can silently permit a request the backend blocks, and vice versa.
 */
export function getReplayVisionEditDisabledReason(scannerUserAccessLevel?: AccessControlLevel | null): string | null {
    return (
        getAccessControlDisabledReason(
            AccessControlResourceType.ReplayScanner,
            AccessControlLevel.Editor,
            scannerUserAccessLevel ?? undefined
        ) ?? getAccessControlDisabledReason(AccessControlResourceType.SessionRecording, AccessControlLevel.Viewer)
    )
}

/**
 * Reading recording-derived content (e.g. drilling from a scanner chart into the sessions behind a data
 * point) requires session_recording viewer access, independent of scanner access. A scanner-only viewer
 * denied recordings must not be able to enumerate them, so gate any recording-surfacing affordance on this.
 */
export function getReplayVisionRecordingViewDisabledReason(): string | null {
    return getAccessControlDisabledReason(AccessControlResourceType.SessionRecording, AccessControlLevel.Viewer) ?? null
}

/**
 * Deleting a scanner or vision action is the one write that skips the session_recording check —
 * destroy doesn't expose or process recording content (see `_CONFIG_ACTIONS`, which omits "destroy",
 * in ReplayScannerViewSet/VisionActionViewSet). Kept as its own export so delete call sites are
 * explicit about needing the narrower bar, rather than reusing the general helper and getting it
 * right by accident.
 */
export function getReplayVisionDeleteDisabledReason(scannerUserAccessLevel?: AccessControlLevel | null): string | null {
    return getAccessControlDisabledReason(
        AccessControlResourceType.ReplayScanner,
        AccessControlLevel.Editor,
        scannerUserAccessLevel ?? undefined
    )
}
