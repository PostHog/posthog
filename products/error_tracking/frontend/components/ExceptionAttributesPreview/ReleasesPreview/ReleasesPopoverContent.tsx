import { useValues } from 'kea'

import { IconCopy, IconExternal } from '@posthog/icons'
import { LemonButton, LemonTag } from '@posthog/lemon-ui'

import { ExceptionRelease } from 'lib/components/Errors/types'
import { Link } from 'lib/lemon-ui/Link'
import { copyToClipboard } from 'lib/utils/copyToClipboard'

import { ReleasePreviewOutput, releasePreviewLogic } from './releasePreviewLogic'

export interface ReleasesPopoverContentProps {
    releasePreviewData: ReleasePreviewOutput
}

export function ReleasePopoverContent({}: ReleasesPopoverContentProps): JSX.Element {
    const { releasePreviewData } = useValues(releasePreviewLogic)

    const title = 'Related release'

    return (
        <div className="min-w-[20rem] max-w-[20rem] overflow-hidden">
            <div className="border-b-1 p-2">
                <h4 className="mb-0">{title}</h4>
            </div>
            <div className="p-2">
                <MostProbableRelease release={releasePreviewData.mostProbableRelease} />
            </div>
        </div>
    )
}

function MostProbableRelease({ release }: { release: ExceptionRelease }): JSX.Element {
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
