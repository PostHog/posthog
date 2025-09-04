import { IconCopy, IconExternal } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { ExceptionRelease } from 'lib/components/Errors/types'
import { Link } from 'lib/lemon-ui/Link'
import { copyToClipboard } from 'lib/utils/copyToClipboard'

export interface ReleasesPopoverContentProps {
    releases: ExceptionRelease[]
}

export function ReleasesPopoverContent({ releases }: ReleasesPopoverContentProps): JSX.Element {
    return (
        <div className="min-w-[24rem] max-w-[40rem]">
            <div className="flex justify-between items-center border-b-1 p-2">
                <h4 className="mb-0">Related releases</h4>
            </div>
            <div className="p-2 space-y-3">
                {releases.map((r, idx) => (
                    <div key={r.commitSha} className="space-y-2">
                        <div className="flex items-center gap-2">
                            <div className="w-28 text-xs text-muted">Commit SHA</div>
                            <div className="flex-1 flex items-center gap-2 min-w-0">
                                <div className="font-mono text-xs break-all" title={r.commitSha}>
                                    {r.commitSha.slice(0, 7)}...
                                </div>
                                <LemonButton
                                    size="xsmall"
                                    icon={<IconCopy />}
                                    tooltip="Copy commit SHA"
                                    onClick={() => copyToClipboard(r.commitSha)}
                                />
                            </div>
                        </div>
                        {r.url && (
                            <div className="flex items-center gap-2">
                                <div className="w-28 text-xs text-muted">URL</div>
                                <div className="flex-1 min-w-0">
                                    <Link
                                        to={r.url}
                                        target="_blank"
                                        className="text-xs break-all inline-flex items-center gap-1"
                                    >
                                        <span className="truncate" title={r.url}>
                                            {r.url}
                                        </span>
                                        <IconExternal className="size-3" />
                                    </Link>
                                </div>
                            </div>
                        )}
                        {idx < releases.length - 1 && <div className="-mx-2 border-t-1" />}
                    </div>
                ))}
            </div>
        </div>
    )
}
