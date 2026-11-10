import posthog from 'posthog-js'

import type { ArtifactPreviewKind } from './taskRunArtifacts'

export interface ArtifactChipClick {
    kind: ArtifactPreviewKind
    inOverflow: boolean
    fileCount: number
    surface: 'space_feed'
}

export function captureArtifactChipClicked({ kind, inOverflow, fileCount, surface }: ArtifactChipClick): void {
    // pinned: analytics event name and properties. Renaming them breaks insights.
    posthog.capture('task artifact chip clicked', {
        kind,
        in_overflow: inOverflow,
        file_count: fileCount,
        surface,
    })
}
