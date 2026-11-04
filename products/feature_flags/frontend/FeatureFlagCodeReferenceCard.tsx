import { LemonCard, LemonTag, Link } from '@posthog/lemon-ui'

import { CodeSnippet, getLanguage } from 'lib/components/CodeSnippet'

import type { FeatureFlagCodeBranchApi, FeatureFlagCodeReferenceApi } from './generated/api.schemas'

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
    const language = getLanguage(reference.file.split('.').pop()?.toLowerCase() ?? '')
    const fileUrl = `https://github.com/${repository}/blob/${commitSha}/${reference.file}#L${reference.check_line}`

    return (
        <LemonCard hoverEffect={false} className="@container p-4 flex flex-col gap-3">
            <div className="flex flex-col gap-1 min-w-0">
                <Link
                    to={fileUrl}
                    target="_blank"
                    className="font-mono font-semibold break-all"
                    onClick={onGitHubLinkClick}
                    data-attr="feature-flag-code-analysis-github-link"
                >
                    {reference.file}:{reference.check_line}
                </Link>
                <div className="text-secondary text-sm">
                    Checked with <code>{reference.method}</code>
                </div>
                <p className="m-0">{reference.summary}</p>
            </div>
            <div className="grid grid-cols-1 @2xl:grid-cols-2 gap-3">
                {reference.branches.map((branch, index) => (
                    <FeatureFlagCodeBranch
                        key={`${branch.variant}-${branch.start_line}-${index}`}
                        branch={branch}
                        language={language}
                    />
                ))}
            </div>
        </LemonCard>
    )
}

function FeatureFlagCodeBranch({
    branch,
    language,
}: {
    branch: FeatureFlagCodeBranchApi
    language: ReturnType<typeof getLanguage>
}): JSX.Element {
    // "all" marks code that runs for every outcome, with only the flag value passed to it changing.
    const isEveryOutcome = branch.variant === 'all'
    return (
        <div className={`flex flex-col gap-1 min-w-0${isEveryOutcome ? ' @2xl:col-span-2' : ''}`}>
            <div className="flex items-center justify-between gap-2">
                <LemonTag
                    type={isEveryOutcome ? 'default' : branch.variant === 'disabled' ? 'muted' : 'success'}
                    className={isEveryOutcome ? undefined : 'font-mono'}
                >
                    {isEveryOutcome ? 'Every outcome' : branch.variant}
                </LemonTag>
                <span className="text-secondary text-xs">
                    {branch.start_line === branch.end_line
                        ? `Line ${branch.start_line}`
                        : `Lines ${branch.start_line}-${branch.end_line}`}
                </span>
            </div>
            {branch.snippet ? (
                <CodeSnippet language={language} compact thing="code" maxLinesWithoutExpansion={20}>
                    {branch.snippet}
                </CodeSnippet>
            ) : (
                <div className="text-secondary text-sm italic border border-dashed rounded p-2">
                    No code runs for this outcome.
                </div>
            )}
        </div>
    )
}
