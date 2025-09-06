import { useValues } from 'kea'

import { IconCommit, IconExternal, IconGitBranch, IconGitRepository } from '@posthog/icons'
import { LemonButton, LemonTag } from '@posthog/lemon-ui'

import { ExceptionReleaseGitMeta } from 'lib/components/Errors/types'
import { copyToClipboard } from 'lib/utils/copyToClipboard'

import { ReleasePreviewOutput, releasePreviewLogic } from './releasePreviewLogic'

export interface ReleasesPopoverContentProps {
    releasePreviewData: ReleasePreviewOutput
}

export function ReleasePopoverContent({}: ReleasesPopoverContentProps): JSX.Element {
    const { releasePreviewData } = useValues(releasePreviewLogic)

    const title = 'Related release'

    return (
        <div className="overflow-hidden">
            <div className="border-b-1 p-2 flex items-center justify-between gap-3">
                <h4 className="mb-0">{title}</h4>
                {releasePreviewData.mostProbableRelease?.repositoryUrl && (
                    <LemonButton
                        to={releasePreviewData.mostProbableRelease.repositoryUrl}
                        targetBlank
                        size="xsmall"
                        type="secondary"
                        icon={<IconExternal />}
                    >
                        Open commit
                    </LemonButton>
                )}
            </div>
            <div className="p-2">
                <MostProbableRelease release={releasePreviewData.mostProbableRelease!} />
            </div>
        </div>
    )
}

function MostProbableRelease({ release }: { release: ExceptionReleaseGitMeta }): JSX.Element {
    return (
        <div className="space-y-3">
            {/* First row: Commit and Branch pills */}
            <div className="flex items-center gap-2 flex-wrap">
                <LemonTag
                    className="bg-fill-primary font-mono text-xs cursor-pointer hover:bg-fill-secondary"
                    onClick={() => copyToClipboard(release.commitSha, 'full commit SHA')}
                >
                    <IconCommit className="text-sm text-secondary" />
                    <span title={`${release.commitSha} (click to copy)`}>{release.commitSha.slice(0, 7)}</span>
                </LemonTag>
                {release.branch && (
                    <LemonTag className="bg-fill-primary text-xs">
                        <IconGitBranch className="text-sm text-secondary" />
                        <span title={release.branch}>{release.branch}</span>
                    </LemonTag>
                )}
            </div>

            {/* Second row: Repository pill */}
            {release.repositoryName && (
                <div className="flex items-center gap-2">
                    <LemonTag className="bg-fill-primary text-xs">
                        <IconGitRepository className="text-sm text-secondary" />
                        <span title={release.repositoryName}>{release.repositoryName}</span>
                    </LemonTag>
                </div>
            )}
        </div>
    )
}
