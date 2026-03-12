import { useActions } from 'kea'
import { ReactNode } from 'react'

import { IconDirectedGraph, IconOpenSidebar } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { getRuntimeFromLib } from 'lib/components/Errors/utils'
import { TZLabel } from 'lib/components/TZLabel'
import { sceneLogic } from 'scenes/sceneLogic'
import { urls } from 'scenes/urls'

import { ErrorTrackingIssue } from '~/queries/schema/schema-general'
import { SimilarIssue } from '~/queries/schema/schema-general'

import { StatusIndicator } from './Indicators'
import { RuntimeIcon } from './RuntimeIcon'
import { CustomSeparator } from './TableColumns'

export default function SimilarIssueCard({
    issue,
    onClick,
    actions,
}: {
    issue: SimilarIssue
    onClick: (e: React.MouseEvent<HTMLDivElement>) => void
    actions: ReactNode
}): JSX.Element {
    const runtime = getRuntimeFromLib(issue.library)
    return (
        <div className="flex items-start gap-x-2 group/card px-2 py-1.5">
            <div className="flex flex-col min-w-0 gap-1 flex-grow cursor-pointer group/content" onClick={onClick}>
                <div className="flex items-center gap-2">
                    <RuntimeIcon
                        className="shrink-0 group-hover/content:text-accent"
                        runtime={runtime}
                        fontSize="0.7rem"
                    />
                    <span className="font-semibold text-base line-clamp-1 group-hover/content:text-accent text-sm">
                        {issue.name || 'Unknown Type'}
                    </span>
                </div>
                {issue.description && (
                    <div title={issue.description} className="line-clamp-1 text-[var(--gray-8)] text-xs font-normal">
                        {issue.description}
                    </div>
                )}
                <div className="flex items-center text-secondary">
                    <StatusIndicator
                        status={issue.status as ErrorTrackingIssue['status']}
                        className="text-xs"
                        size="xsmall"
                    />
                    <CustomSeparator />
                    <TZLabel time={issue.first_seen} className="border-dotted border-b text-xs ml-1" delayMs={750} />
                </div>
            </div>
            <div className="shrink-0 flex items-center gap-1 opacity-0 group-hover/card:opacity-100 transition-opacity">
                <OpenInNewTabAction issueId={issue.id} />
                {actions}
            </div>
        </div>
    )
}

function OpenInNewTabAction({ issueId }: { issueId: string }): JSX.Element {
    const { newTab } = useActions(sceneLogic)
    return (
        <LemonButton
            type="secondary"
            size="xsmall"
            icon={<IconOpenSidebar />}
            onClick={() => newTab(urls.errorTrackingIssue(issueId))}
            tooltip="Open in new tab"
        />
    )
}

export function MergeAction({ onClick }: { onClick: () => void }): JSX.Element {
    return (
        <LemonButton
            type="primary"
            size="xsmall"
            icon={<IconDirectedGraph />}
            onClick={onClick}
            tooltip="Merge this issue into the current one"
            tooltipDocLink="https://posthog.com/docs/error-tracking/fingerprints"
        />
    )
}
