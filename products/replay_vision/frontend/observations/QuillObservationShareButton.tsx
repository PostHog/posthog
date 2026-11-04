import { IconShare } from '@posthog/icons'
import { Button } from '@posthog/quill'

import { ObservationShareButtonProps, openObservationShareDialog } from './ObservationShareButton'

export function QuillObservationShareButton(props: ObservationShareButtonProps): JSX.Element {
    return (
        <Button
            variant="outline"
            tooltip="Copy a link to this observation, starting the recording where you are"
            data-attr="vision-observation-share"
            onClick={() => openObservationShareDialog(props)}
        >
            <IconShare />
            Share
        </Button>
    )
}
