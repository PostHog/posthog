import { IconX } from '@posthog/icons'
import { LemonButton, LemonMenu } from '@posthog/lemon-ui'

import type { FeedDismissalReasonEnumApi } from '../../generated/api.schemas'
import { feedDismissalMenuItems } from '../highlightFeedDismissal'

interface HighlightFeedDismissButtonProps {
    onDismiss: (reason: FeedDismissalReasonEnumApi | null) => void
    className?: string
}

export function HighlightFeedDismissButton({ onDismiss, className }: HighlightFeedDismissButtonProps): JSX.Element {
    return (
        <LemonMenu placement="bottom-end" items={feedDismissalMenuItems(onDismiss)}>
            <LemonButton
                size="xsmall"
                icon={<IconX />}
                tooltip="Not useful"
                aria-label="Not useful"
                className={className}
                data-attr="vision-highlight-feed-dismiss"
            />
        </LemonMenu>
    )
}
