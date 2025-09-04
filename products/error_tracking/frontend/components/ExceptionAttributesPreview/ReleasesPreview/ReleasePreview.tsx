import { useValues } from 'kea'
import { useState } from 'react'

import { IconCommit } from '@posthog/icons'
import { LemonTag, Popover } from '@posthog/lemon-ui'

import { ReleasePopoverContent } from './ReleasesPopoverContent'
import { releasePreviewLogic } from './releasePreviewLogic'

export function ReleasePreview(): JSX.Element {
    const [isOpen, setIsOpen] = useState(false)
    const { releasePreviewData } = useValues(releasePreviewLogic)

    return (
        <Popover
            visible={isOpen}
            overlay={<ReleasePopoverContent releasePreviewData={releasePreviewData} />}
            placement="right"
            padded={false}
            showArrow
            onMouseEnterInside={() => setIsOpen(true)}
            onMouseLeaveInside={() => setIsOpen(false)}
        >
            <span
                className="inline-flex align-middle"
                onMouseEnter={() => setIsOpen(true)}
                onMouseLeave={() => setIsOpen(false)}
            >
                <LemonTag
                    className="bg-fill-primary"
                    onMouseEnter={() => setIsOpen(true)}
                    onMouseLeave={() => setIsOpen(false)}
                >
                    <IconCommit className="text-sm text-secondary" />
                    <span>{releasePreviewData.mostProbableRelease.commitSha.slice(0, 7)}</span>
                </LemonTag>
            </span>
        </Popover>
    )
}
