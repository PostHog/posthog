import clsx from 'clsx'

import { LemonCard, Link } from '@posthog/lemon-ui'

import { FeatureFlagCodeOutcome } from './FeatureFlagCodeOutcome'
import { languageForFile, sortBranches } from './featureFlagCodeSnippets'
import type { FeatureFlagCodeReferenceApi } from './generated/api.schemas'

export interface FeatureFlagCodeReferenceCardProps {
    reference: FeatureFlagCodeReferenceApi
    repository: string
    commitSha: string
    onGitHubLinkClick: () => void
}

export function FeatureFlagCodeReferenceCard({
    reference,
    repository,
    commitSha,
    onGitHubLinkClick,
}: FeatureFlagCodeReferenceCardProps): JSX.Element {
    const language = languageForFile(reference.file)
    const fileUrl = `https://github.com/${repository}/blob/${commitSha}/${reference.file}#L${reference.check_line}`
    const branches = sortBranches(reference.branches)

    return (
        <LemonCard hoverEffect={false} className="@container p-0 overflow-hidden">
            <div className="flex flex-col gap-1 min-w-0 p-3 border-b">
                <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
                    <Link
                        to={fileUrl}
                        target="_blank"
                        className="font-mono font-semibold break-all"
                        onClick={onGitHubLinkClick}
                        data-attr="feature-flag-code-analysis-github-link"
                    >
                        {reference.file}:{reference.check_line}
                    </Link>
                    <span className="text-secondary text-xs">
                        Checked with <code>{reference.method}</code>
                    </span>
                </div>
                <p className="m-0">{reference.summary}</p>
            </div>
            {/* gap-px over a border-colored background draws the dividers between however many panes wrap. */}
            <div
                className={clsx('grid grid-cols-1 gap-px bg-border-primary', branches.length > 1 && '@2xl:grid-cols-2')}
            >
                {branches.map((branch, index) => (
                    <FeatureFlagCodeOutcome
                        key={`${branch.variant}-${branch.start_line}-${index}`}
                        branch={branch}
                        language={language}
                        className={
                            branches.length % 2 === 1 && index === branches.length - 1 ? '@2xl:col-span-2' : undefined
                        }
                    />
                ))}
            </div>
        </LemonCard>
    )
}
