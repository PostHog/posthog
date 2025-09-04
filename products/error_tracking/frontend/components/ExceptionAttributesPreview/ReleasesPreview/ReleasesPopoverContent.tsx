import { useValues } from 'kea'
import { useMemo } from 'react'

import { IconCopy, IconExternal } from '@posthog/icons'
import { LemonButton, LemonTag } from '@posthog/lemon-ui'

import { stackFrameLogic } from 'lib/components/Errors/stackFrameLogic'
import { ErrorTrackingStackFrameRecord, ExceptionRelease } from 'lib/components/Errors/types'
import { Link } from 'lib/lemon-ui/Link'
import { copyToClipboard } from 'lib/utils/copyToClipboard'

export interface ReleasesPopoverContentProps {
    releases: ExceptionRelease[]
}

export function ReleasePopoverContent({ releases }: ReleasesPopoverContentProps): JSX.Element {
    const title = releases.length === 1 ? 'Related release' : 'Related releases'

    return (
        <div className="min-w-[20rem] max-w-[20rem] overflow-hidden">
            <div className="border-b-1 p-2">
                <h4 className="mb-0">{title}</h4>
            </div>
            <ReleasesList releases={releases} />
        </div>
    )
}

function ReleasesList({ releases }: { releases: ExceptionRelease[] }): JSX.Element {
    return (
        <div className="p-2">
            {releases.map((release, idx) => (
                <div key={release.commitSha}>
                    <ReleaseListItem release={release} />
                    {idx < releases.length - 1 && <div className="border-t-1 my-2" />}
                </div>
            ))}
        </div>
    )
}

function SimplePropertyRow({ label, value }: { label: string; value?: string }): JSX.Element {
    if (!value) {
        return <></>
    }

    return (
        <div className="flex items-center gap-2">
            <div className="w-20 text-xs text-muted">{label}</div>
            <div className="flex-1 min-w-0">
                <span className="text-xs block truncate max-w-full" title={value}>
                    {value}
                </span>
            </div>
        </div>
    )
}

function ReleaseListItem({ release }: { release: ExceptionRelease }): JSX.Element {
    const { stackFrameRecords } = useValues(stackFrameLogic)

    const kaboomFrame: ErrorTrackingStackFrameRecord | undefined = useMemo(() => {
        const framesInOrder = Object.getOwnPropertyNames(stackFrameRecords).map((k) => stackFrameRecords[k])

        for (let i = framesInOrder.length - 1; i >= 0; i--) {
            const frame = framesInOrder[i]
            if (frame.resolved && frame.contents.in_app) {
                return frame
            }
        }

        return undefined
    }, [stackFrameRecords])

    return (
        <div className="space-y-2">
            <div className="flex items-center gap-2">
                <div className="w-20 text-xs text-muted">Commit SHA</div>
                <div className="flex-1 flex items-center gap-2 min-w-0">
                    <LemonTag className="bg-fill-primary font-mono text-xs flex-1 min-w-0">
                        <span className="block truncate max-w-full" title={release.commitSha}>
                            {release.commitSha}
                        </span>
                    </LemonTag>
                    <LemonButton
                        size="xsmall"
                        icon={<IconCopy />}
                        tooltip="Copy full commit SHA"
                        onClick={() => copyToClipboard(release.commitSha, 'full commit SHA')}
                    />
                </div>
            </div>
            {release.repositoryUrl && (
                <div className="flex items-center gap-2">
                    <div className="w-20 text-xs text-muted">URL</div>
                    <div className="flex-1 flex min-w-0 items-center gap-2">
                        <Link
                            to={release.repositoryUrl}
                            target="_blank"
                            className="text-xs inline-flex items-center gap-1 min-w-0 w-full"
                        >
                            <span className="flex-1 truncate max-w-full" title={release.repositoryUrl}>
                                {release.repositoryUrl}
                            </span>
                            <IconExternal className="shrink-0" />
                        </Link>
                    </div>
                </div>
            )}
            <SimplePropertyRow label="Repository" value={release.repositoryName} />
            <SimplePropertyRow label="Branch" value={release.branch} />
            <div>
                <span>Kaboom stack frame record:</span>
                <span>{kaboomFrame && kaboomFrame.contents.line}</span>
            </div>
        </div>
    )
}
