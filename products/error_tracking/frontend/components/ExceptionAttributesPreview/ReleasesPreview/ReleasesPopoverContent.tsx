import { ReactNode, createElement, useMemo } from 'react'
import { P, match } from 'ts-pattern'

import { IconCommit, IconGitBranch, IconGitRepository, IconShare } from '@posthog/icons'
import { IconComponent, IconProps } from '@posthog/icons/dist/src/types/icon-types'
import { LemonTag, LemonTagProps, Link, Tooltip } from '@posthog/lemon-ui'

import { ErrorTrackingRelease, ReleaseGitMetadata } from 'lib/components/Errors/types'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { cn } from 'lib/utils/css-classes'

import { GitMetadataParser } from './gitMetadataParser'

export interface ReleasesPopoverContentProps {
    release: ErrorTrackingRelease
}

export function ReleasePopoverContent({ release }: ReleasesPopoverContentProps): JSX.Element {
    return (
        <div className="overflow-hidden">
            <div className="p-2">
                <div className="pb-1 text-secondary text-xs">Release</div>
                <table className="justify-between w-full text-left items-center min-w-[180px]">
                    <tr>
                        <th className="pb-1">Project</th>
                        <td className="pb-1 text-right">{release.project ?? 'Unknown'}</td>
                    </tr>
                    <tr>
                        <th>Version</th>
                        <td className="text-right">{release.version.slice(0, 10)}</td>
                    </tr>
                </table>
            </div>
            {match(release?.metadata?.git)
                .with(P.nullish, () => <></>)
                .otherwise((git) => (
                    <GitFooter git={git} />
                ))}
        </div>
    )
}

function GitFooter({ git }: { git: ReleaseGitMetadata }): JSX.Element {
    let { commit_id, branch, remote_url } = git
    const viewCommitLink = useMemo(() => GitMetadataParser.getViewCommitLink(git), [git])
    const parsedRemoteUrl = useMemo(
        () => (remote_url ? GitMetadataParser.parseRemoteUrl(remote_url) : null),
        [remote_url]
    )
    return (
        <div className="border-t-1 p-1 bg-fill-primary">
            <div className="flex items-center gap-1 flex-wrap">
                {commit_id && (
                    <PropertyDisplay
                        icon={IconCommit}
                        tooltip="Copy commit SHA"
                        onClick={() => copyToClipboard(commit_id, 'full commit SHA')}
                    >
                        {commitDisplay(commit_id)}
                    </PropertyDisplay>
                )}
                {branch && (
                    <PropertyDisplay
                        icon={IconGitBranch}
                        tooltip="Copy branch name"
                        onClick={() => copyToClipboard(branch, 'branch name')}
                    >
                        {branch}
                    </PropertyDisplay>
                )}
                {remote_url && parsedRemoteUrl && (
                    <PropertyDisplay
                        icon={IconGitRepository}
                        tooltip="Copy remote URL"
                        onClick={() => copyToClipboard(remote_url, 'remote url')}
                    >
                        {`${parsedRemoteUrl.owner}/${parsedRemoteUrl.repository}`}
                    </PropertyDisplay>
                )}
                <Link to={viewCommitLink} target="_blank">
                    <ButtonPrimitive size="xs" tooltip="Open commit in GitHub" className="text-accent">
                        <IconShare />
                    </ButtonPrimitive>
                </Link>
            </div>
        </div>
    )
}

function PropertyDisplay({
    icon,
    children,
    tooltip,
    ...tagProps
}: {
    icon: IconComponent<IconProps>
    children: ReactNode
    tooltip?: string
} & Omit<LemonTagProps, 'icon'>): JSX.Element {
    function renderContent(): JSX.Element {
        return (
            <LemonTag
                className={cn('bg-fill-primary cursor-pointer hover:bg-fill-secondary', tagProps.className)}
                {...tagProps}
            >
                {icon && createElement(icon, { className: 'text-sm text-secondary' })}
                <span>{children}</span>
            </LemonTag>
        )
    }

    function maybeWrapWithTooltip(content: JSX.Element, tooltip?: string): JSX.Element {
        return tooltip ? <Tooltip title={tooltip}>{content}</Tooltip> : content
    }

    return maybeWrapWithTooltip(renderContent(), tooltip)
}

function commitDisplay(commit: string): string {
    return commit.slice(0, 7)
}
