import { IconCommit } from '@posthog/icons'
import { Badge } from '@posthog/quill'

import { ErrorTrackingRelease } from 'lib/components/Errors/types'
import { QuillHoverCard } from 'lib/components/QuillHoverCard/QuillHoverCard'

import { QuillReleasePopoverContent } from './QuillReleasePopoverContent'
import { releasePillTitle } from './ReleasePreviewPill'

export function QuillReleasePreviewPill({ release }: { release: ErrorTrackingRelease }): JSX.Element {
    return (
        <QuillHoverCard side="right" content={<QuillReleasePopoverContent release={release} />}>
            <Badge translate="no">
                <IconCommit />
                <span>{releasePillTitle(release)}</span>
            </Badge>
        </QuillHoverCard>
    )
}
