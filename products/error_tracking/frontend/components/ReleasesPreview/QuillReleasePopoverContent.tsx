import { useMemo } from 'react'

import { IconCommit, IconGitBranch, IconGitRepository, IconShare } from '@posthog/icons'
import { Button, Separator, Text, Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill'

import { ErrorTrackingRelease, ReleaseGitMetadata } from 'lib/components/Errors/types'
import { GitMetadataParser } from 'lib/components/Git/gitMetadataParser'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { copyToClipboard } from 'lib/utils/copyToClipboard'

import { commitDisplay, versionDisplay } from './ReleasesPopoverContent'

export function QuillReleasePopoverContent({ release }: { release: ErrorTrackingRelease }): JSX.Element {
    const [displayVersion, build] = release.version.includes('+')
        ? release.version.split('+', 2)
        : [release.version, null]
    const version = versionDisplay(displayVersion)

    return (
        <div className="flex min-w-48 flex-col gap-2">
            <Text size="xs" variant="muted" render={<span className="m-0" />}>
                Release
            </Text>
            <dl className="m-0 grid grid-cols-2 gap-x-4 gap-y-1">
                <Text size="xs" weight="medium" render={<dt />}>
                    Project
                </Text>
                <Text size="xs" render={<dd className="m-0 text-right" />}>
                    {release.project ?? 'Unknown'}
                </Text>
                <Text size="xs" weight="medium" render={<dt />}>
                    Version
                </Text>
                <Text size="xs" render={<dd className="m-0 text-right" />}>
                    {version.truncated ? (
                        <Tooltip>
                            <TooltipTrigger render={<span />}>{version.display}</TooltipTrigger>
                            <TooltipContent>{displayVersion}</TooltipContent>
                        </Tooltip>
                    ) : (
                        version.display
                    )}
                </Text>
                {build && (
                    <>
                        <Text size="xs" weight="medium" render={<dt />}>
                            Build
                        </Text>
                        <Text size="xs" render={<dd className="m-0 text-right" />}>
                            {build}
                        </Text>
                    </>
                )}
            </dl>
            {release.metadata?.git && <QuillReleaseGitFooter git={release.metadata.git} />}
        </div>
    )
}

function QuillReleaseGitFooter({ git }: { git: ReleaseGitMetadata }): JSX.Element {
    const { commit_id, branch, remote_url } = git
    const viewCommitLink = useMemo(() => GitMetadataParser.getCommitLink(git.remote_url, git.commit_id), [git])
    const parsedRemoteUrl = useMemo(
        () => (remote_url ? GitMetadataParser.parseRemoteUrl(remote_url) : null),
        [remote_url]
    )

    return (
        <>
            <Separator />
            <div className="flex flex-wrap items-center gap-1">
                {commit_id && (
                    <Button
                        variant="outline"
                        size="xs"
                        tooltip="Copy commit SHA"
                        onClick={() => copyToClipboard(commit_id, 'full commit SHA')}
                    >
                        <IconCommit />
                        {commitDisplay(commit_id)}
                    </Button>
                )}
                {branch && (
                    <Button
                        variant="outline"
                        size="xs"
                        tooltip="Copy branch name"
                        onClick={() => copyToClipboard(branch, 'branch name')}
                    >
                        <IconGitBranch />
                        {branch}
                    </Button>
                )}
                {remote_url && parsedRemoteUrl && (
                    <Button
                        variant="outline"
                        size="xs"
                        tooltip="Copy remote URL"
                        onClick={() => copyToClipboard(remote_url, 'remote url')}
                    >
                        <IconGitRepository />
                        {`${parsedRemoteUrl.owner}/${parsedRemoteUrl.repository}`}
                    </Button>
                )}
                {viewCommitLink && (
                    <Button
                        size="icon-xs"
                        aria-label="Open commit in GitHub"
                        tooltip="Open commit in GitHub"
                        nativeButton={false}
                        render={<LinkPrimitive to={viewCommitLink} target="_blank" />}
                    >
                        <IconShare />
                    </Button>
                )}
            </div>
        </>
    )
}
