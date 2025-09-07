import { useActions, useValues } from 'kea'
import { useEffect, useState } from 'react'

import { IconCommit } from '@posthog/icons'
import { LemonTag, Popover } from '@posthog/lemon-ui'

import { errorPropertiesLogic } from 'lib/components/Errors/errorPropertiesLogic'
import { ParsedEventExceptionRelease } from 'lib/components/Errors/types'

import { ReleasePopoverContent } from './ReleasesPopoverContent'
import { releasePreviewLogic } from './releasePreviewLogic'

export interface ReleasePreviewProps {
    exceptionReleases?: ParsedEventExceptionRelease[]
}

export function ReleasePreview({ exceptionReleases }: ReleasePreviewProps): JSX.Element {
    const [isOpen, setIsOpen] = useState(false)
    const { releasePreviewData } = useValues(releasePreviewLogic)
    const { frames } = useValues(errorPropertiesLogic)
    const { loadRelease } = useActions(releasePreviewLogic)

    useEffect(() => {
        loadRelease({ exceptionReleases, frames })
    }, [frames, loadRelease, exceptionReleases])

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
                    <span>{releasePillTitle(releasePreviewData.mostProbableRelease)}</span>
                </LemonTag>
            </span>
        </Popover>
    )
}

function releasePillTitle(release: ParsedEventExceptionRelease): string {
    return release.metadata?.git?.commitId?.slice(0, 7) ?? release.version.slice(0, 7) ?? ''
}
