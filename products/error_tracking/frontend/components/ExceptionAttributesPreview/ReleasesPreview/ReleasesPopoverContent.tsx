import { IconCommit, IconExternal, IconGitBranch, IconGitRepository, IconInfo } from '@posthog/icons'
import { LemonButton, LemonTag, Tooltip } from '@posthog/lemon-ui'

import { ParsedEventExceptionRelease } from 'lib/components/Errors/types'
import { copyToClipboard } from 'lib/utils/copyToClipboard'

import { GitMetadataParser } from './gitMetadataParser'

export interface ReleasesPopoverContentProps {
    release: ParsedEventExceptionRelease
}

export function ReleasePopoverContent({ release }: ReleasesPopoverContentProps): JSX.Element {
    const viewCommitLink = GitMetadataParser.getViewCommitLink(release)

    return (
        <div className="overflow-hidden">
            <div className="border-b-1 p-2 flex items-center justify-between gap-3">
                <h4 className="mb-0">Related release</h4>
                {viewCommitLink && (
                    <LemonButton to={viewCommitLink} targetBlank size="xsmall" type="secondary" icon={<IconExternal />}>
                        View commit
                    </LemonButton>
                )}
            </div>
            <div className="p-2">
                {release?.metadata?.git ? <GitRelease release={release} /> : <GitlessRelease release={release} />}
            </div>
        </div>
    )
}

function GitRelease({ release }: { release: ParsedEventExceptionRelease }): JSX.Element {
    return (
        <div>
            <div className="flex items-center gap-2 flex-wrap">
                <Tooltip title="Click to copy full commit SHA to clipboard">
                    <LemonTag
                        className="bg-fill-primary font-mono text-xs cursor-pointer hover:bg-fill-secondary"
                        onClick={() => copyToClipboard(release.metadata?.git?.commitId ?? '', 'full commit SHA')}
                    >
                        <IconCommit className="text-sm text-secondary" />
                        <span title={`${release.metadata?.git?.commitId ?? ''} (click to copy)`}>
                            {release.metadata?.git?.commitId?.slice(0, 7)}
                        </span>
                    </LemonTag>
                </Tooltip>
                {release.metadata?.git?.branch && (
                    <Tooltip title="Git branch name">
                        <LemonTag className="bg-fill-primary text-xs">
                            <IconGitBranch className="text-sm text-secondary" />
                            <span title={release.metadata?.git?.branch}>{release.metadata?.git?.branch}</span>
                        </LemonTag>
                    </Tooltip>
                )}
                {release.metadata?.git?.repoName && (
                    <Tooltip title="Git repository name">
                        <LemonTag className="bg-fill-primary text-xs">
                            <IconGitRepository className="text-sm text-secondary" />
                            <span title={release.metadata?.git?.repoName}>{release.metadata?.git?.repoName}</span>
                        </LemonTag>
                    </Tooltip>
                )}
            </div>
        </div>
    )
}

function GitlessRelease({ release }: { release: ParsedEventExceptionRelease }): JSX.Element {
    return (
        <div className="flex items-center justify-between gap-2">
            <LemonTag className="bg-fill-primary text-xs">
                <IconCommit className="text-sm text-secondary" />
                <span>{release.version}</span>
            </LemonTag>
            <Tooltip title="No git release information available. Version you see was manually provided by you using '--version' flag in the 'upload' CLI command">
                <IconInfo className="text-muted-alt" />
            </Tooltip>
        </div>
    )
}
