import { useActions, useValues } from 'kea'

import { IconX } from '@posthog/icons'
import { Button } from '@posthog/quill'

import { releaseLogic } from './releaseLogic'
import { releaseRelatedLogic } from './releaseRelatedLogic'
import { Lane } from './releaseTracks'
import { ReleaseRow } from './releaseUtils'

export function ReleaseLaneRemoveButton({ row, lane }: { row: ReleaseRow; lane: Lane }): JSX.Element | null {
    const { canEditReleases } = useValues(releaseLogic)
    const { unlinkBroadcast } = useActions(releaseLogic)
    const { unlinkRelated } = useActions(releaseRelatedLogic)

    if (!canEditReleases || (lane.kind !== 'survey' && lane.kind !== 'broadcast')) {
        return null
    }
    return (
        <Button
            size="icon-xs"
            aria-label={`Remove ${lane.title} from the release`}
            tooltip="Remove from the release"
            onClick={() =>
                lane.kind === 'survey'
                    ? unlinkRelated(row.id, 'survey', lane.survey.id)
                    : unlinkBroadcast(row.id, lane.broadcastId)
            }
            data-attr="release-lane-remove"
        >
            <IconX />
        </Button>
    )
}
