import { useValues } from 'kea'
import { useState } from 'react'

import { IconCommit } from '@posthog/icons'
import { LemonTag, Popover } from '@posthog/lemon-ui'

import { ErrorTrackingRelease } from 'lib/components/Errors/types'

import { ReleasePopoverContent } from './ReleasesPopoverContent'
import { releasePreviewLogic } from './releasePreviewLogic'

export function ReleasePreviewPill(): JSX.Element {
    const [isOpen, setIsOpen] = useState(false)
    const { release } = useValues(releasePreviewLogic)

    if (!release) {
        return <></>
    }

    return (
        <Popover
            visible={isOpen}
            overlay={<ReleasePopoverContent release={release} />}
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
                <LemonTag className="bg-fill-primary">
                    <IconCommit className="text-sm text-secondary" />
                    <span>{releasePillTitle(release)}</span>
                </LemonTag>
            </span>
        </Popover>
    )
}

function releasePillTitle(release: ErrorTrackingRelease): string {
    return release.metadata?.git?.commit_id?.slice(0, 7) ?? release.version ?? ''
}
