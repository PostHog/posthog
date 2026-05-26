import { useValues } from 'kea'

import { IconCopy } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { copyToClipboard } from 'lib/utils/copyToClipboard'

import { userInterviewLogic } from './userInterviewLogic'

export function InterviewLinkCopyButton({ identifier, topicId }: { identifier: string; topicId: string }): JSX.Element {
    const { linkForIdentifier, linksLoading, linksLoadFailed } = useValues(userInterviewLogic({ id: topicId }))
    const interviewUrl = linkForIdentifier(identifier)

    const handleCopy = (e: React.MouseEvent): void => {
        e.preventDefault()
        e.stopPropagation()
        if (!interviewUrl) {
            return
        }
        void copyToClipboard(interviewUrl, 'interview link')
    }

    const disabledReason = interviewUrl
        ? undefined
        : linksLoadFailed
          ? "Couldn't generate link — refresh to retry"
          : linksLoading
            ? 'Generating link…'
            : 'No link available'

    return (
        <LemonButton
            type="tertiary"
            size="xsmall"
            icon={<IconCopy />}
            onClick={handleCopy}
            disabledReason={disabledReason}
            tooltip="Copy interview link"
        />
    )
}
