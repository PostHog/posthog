import { IconCopy, IconExternal } from '@posthog/icons'
import { LemonButton, LemonTag } from '@posthog/lemon-ui'

import { ExceptionRelease } from 'lib/components/Errors/types'
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

function ReleaseListItem({ release }: { release: ExceptionRelease }): JSX.Element {
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
                    <div className="flex-1 min-w-0">
                        <Link
                            to={release.repositoryUrl}
                            target="_blank"
                            className="text-xs inline-flex items-center gap-1 min-w-0 w-full"
                        >
                            <span className="flex-1 truncate max-w-full" title={release.repositoryUrl}>
                                {release.repositoryUrl}
                            </span>
                            <IconExternal className="size-3 shrink-0" />
                        </Link>
                    </div>
                </div>
            )}
        </div>
    )
}
