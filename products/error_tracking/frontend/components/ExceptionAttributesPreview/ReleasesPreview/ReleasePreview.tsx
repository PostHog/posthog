import { useActions, useValues } from 'kea'
import { useEffect, useState } from 'react'

import { IconCommit } from '@posthog/icons'
import { LemonTag, Popover } from '@posthog/lemon-ui'

import { errorPropertiesLogic } from 'lib/components/Errors/errorPropertiesLogic'
import { ExceptionReleaseGitMeta } from 'lib/components/Errors/types'

import { ReleasePopoverContent } from './ReleasesPopoverContent'
import { releasePreviewLogic } from './releasePreviewLogic'

export interface ReleasePreviewProps {
    gitReleasesMeta?: ExceptionReleaseGitMeta[]
}

export function ReleasePreview({ gitReleasesMeta }: ReleasePreviewProps): JSX.Element {
    const [isOpen, setIsOpen] = useState(false)
    const { releasePreviewData } = useValues(releasePreviewLogic)
    const { frames } = useValues(errorPropertiesLogic)
    const { loadRelease } = useActions(releasePreviewLogic)

    useEffect(() => {
        loadRelease({ gitReleasesMeta, frames })
    }, [frames, loadRelease, gitReleasesMeta])

    if (!releasePreviewData.mostProbableRelease) {
        return <></>
    }

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
                    <span>{releasePreviewData.mostProbableRelease?.commitSha?.slice(0, 7)}</span>
                </LemonTag>
            </span>
        </Popover>
    )
}
