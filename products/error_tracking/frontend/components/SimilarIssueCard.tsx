import { ReactNode } from 'node_modules/@types/react'

import { getRuntimeFromLib } from 'lib/components/Errors/utils'

import { SimilarIssue } from '~/queries/schema/schema-general'

import { RuntimeIcon } from './RuntimeIcon'

export default function SimilarIssueCard({
    issue,
    onClick,
    actions,
}: {
    issue: SimilarIssue
    onClick: (e: React.MouseEvent<HTMLDivElement>) => void
    actions: ReactNode
}): JSX.Element {
    const relatedRuntime = getRuntimeFromLib(issue.library)
    return (
        <div className="flex items-center justify-between px-2 py-1 border rounded bg-surface-primary">
            <div className="flex flex-col gap-0.5 min-w-0 group flex-grow cursor-pointer" onClick={onClick}>
                <div className="font-medium flex items-center gap-2 text-sm truncate group-hover:text-accent">
                    <RuntimeIcon runtime={relatedRuntime} fontSize="0.7rem" className="shrink-0" />
                    {issue.name}
                </div>
                {issue.description && <div className="text-xs text-secondary truncate">{issue.description}</div>}
            </div>
            {actions}
        </div>
    )
}
