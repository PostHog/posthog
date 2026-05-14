import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { useMemo, useState } from 'react'

import { IconGithub, IconSidebarClose, IconSidebarOpen } from '@posthog/icons'
import { LemonButton, LemonSkeleton, LemonTag } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { GitHogRiskLevel, GitHogRiskScore, gitHogPullRequestRiskScoreLogic } from './gitHogPullRequestRiskScoreLogic'
import { GitHogPullRequest, GitHogRepoLogicProps, gitHogRepoLogic } from './gitHogRepoLogic'
import { GitHogPRWorkspace } from './widgets/GitHogPRWorkspace'

interface GitHogRepoSceneProps extends GitHogRepoLogicProps {
    number?: number
}

export const scene: SceneExport<GitHogRepoSceneProps> = {
    component: GitHogRepoScene,
    logic: gitHogRepoLogic,
    paramsToProps: ({ params: { owner, name, number } }) => ({
        owner: decodeURIComponent(owner ?? ''),
        name: decodeURIComponent(name ?? ''),
        number: number ? Number(number) : undefined,
    }),
}

const RISK_LABELS: Record<GitHogRiskLevel, { label: string; tag: 'success' | 'warning' | 'danger' | 'default' }> = {
    low: { label: 'Safe', tag: 'success' },
    moderate: { label: 'Medium', tag: 'warning' },
    high: { label: 'High risk', tag: 'danger' },
    critical: { label: 'High risk', tag: 'danger' },
}

function RiskScoreBadge({ owner, name, number }: { owner: string; name: string; number: number }): JSX.Element {
    // Mounts a per-PR risk-score logic on render. The first card to mount a
    // given PR triggers the AJAX load; cached responses come back in one
    // Redis read, uncached ones run the LLM and shimmer until ready.
    const logic = gitHogPullRequestRiskScoreLogic({ owner, name, number })
    const { riskScore, riskScoreLoading } = useValues(logic)

    if (riskScoreLoading && !riskScore) {
        return <LemonSkeleton className="h-5 w-16 rounded-full" title="Assessing risk…" />
    }
    if (!riskScore) {
        return (
            <LemonTag type="default" size="small" title="No assessment available">
                —
            </LemonTag>
        )
    }
    const score = riskScore as GitHogRiskScore
    const styles = RISK_LABELS[score.level] || RISK_LABELS.moderate
    return (
        <LemonTag type={styles.tag} size="small" title={score.headline || styles.label}>
            {styles.label}
        </LemonTag>
    )
}

function PRListItem({
    pr,
    owner,
    name,
    selected,
}: {
    pr: GitHogPullRequest
    owner: string
    name: string
    selected: boolean
}): JSX.Element {
    const { push } = useActions(router)
    const onClick = (): void => {
        push(urls.gitHogPullRequest(owner, name, pr.number))
    }

    return (
        <button
            type="button"
            onClick={onClick}
            className={`w-full text-left px-3 py-2 border-b border-border transition-colors hover:bg-fill-highlight-50 ${
                selected ? 'bg-fill-highlight-100' : 'bg-bg-light'
            }`}
        >
            <div className="flex items-start justify-between gap-2">
                <div className="flex flex-col gap-y-0.5 min-w-0 flex-1">
                    <div className="flex items-baseline gap-x-1.5 min-w-0">
                        <span className="text-sm font-semibold text-primary truncate leading-snug">{pr.title}</span>
                    </div>
                    <div className="flex items-center gap-x-1.5 text-xs text-secondary min-w-0">
                        <span className="text-muted font-mono shrink-0">#{pr.number}</span>
                        {pr.draft && (
                            <LemonTag type="default" size="small">
                                Draft
                            </LemonTag>
                        )}
                        <span className="truncate">{pr.author || 'unknown'}</span>
                        <span className="text-muted">·</span>
                        <TZLabel time={pr.updated_at} />
                    </div>
                </div>
                <div className="shrink-0">
                    <RiskScoreBadge owner={owner} name={name} number={pr.number} />
                </div>
            </div>
        </button>
    )
}

export function GitHogRepoScene({ owner, name, number }: GitHogRepoSceneProps): JSX.Element {
    const { pullRequests, pullRequestsLoading } = useValues(gitHogRepoLogic({ owner, name }))
    const repository = `${owner}/${name}`
    const [inboxCollapsed, setInboxCollapsed] = useState(false)

    const sortedPRs = useMemo(
        () => [...pullRequests].sort((a, b) => new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime()),
        [pullRequests]
    )

    return (
        <SceneContent>
            <SceneTitleSection
                name={repository}
                description="Inbox of open pull requests. Click one to open its review workspace."
                resourceType={{ type: 'githog' }}
                actions={
                    <LemonButton
                        type="secondary"
                        size="small"
                        icon={<IconGithub />}
                        to={`https://github.com/${owner}/${name}`}
                        targetBlank
                    >
                        View on GitHub
                    </LemonButton>
                }
            />
            <div className="flex gap-4 items-start min-h-[60vh]">
                {/* Inbox column — collapses to a narrow rail */}
                {inboxCollapsed ? (
                    <aside className="w-10 shrink-0 border border-border rounded-lg overflow-hidden bg-bg-light flex flex-col items-center py-2 gap-y-2">
                        <LemonButton
                            size="small"
                            type="tertiary"
                            icon={<IconSidebarOpen />}
                            onClick={() => setInboxCollapsed(false)}
                            tooltip="Expand inbox"
                            aria-label="Expand inbox"
                        />
                        {!pullRequestsLoading && (
                            <span
                                className="text-xs text-secondary tabular-nums"
                                title={`${sortedPRs.length} open pull requests`}
                            >
                                {sortedPRs.length}
                            </span>
                        )}
                    </aside>
                ) : (
                    <aside className="w-72 shrink-0 border border-border rounded-lg overflow-hidden bg-bg-light flex flex-col max-h-[80vh]">
                        <div className="px-3 py-1.5 border-b border-border flex items-center justify-between bg-bg-3000 gap-x-2">
                            <div className="flex items-center gap-x-2 min-w-0">
                                <span className="text-sm font-semibold">Pull requests</span>
                                <span className="text-xs text-secondary shrink-0">
                                    {pullRequestsLoading ? 'loading…' : sortedPRs.length}
                                </span>
                            </div>
                            <LemonButton
                                size="xsmall"
                                type="tertiary"
                                icon={<IconSidebarClose />}
                                onClick={() => setInboxCollapsed(true)}
                                tooltip="Collapse inbox"
                                aria-label="Collapse inbox"
                            />
                        </div>
                        <div className="overflow-y-auto flex-1">
                            {pullRequestsLoading && sortedPRs.length === 0 ? (
                                <div className="p-3 flex flex-col gap-y-3">
                                    {[0, 1, 2, 3].map((i) => (
                                        <div key={i} className="flex flex-col gap-y-1.5">
                                            <LemonSkeleton className="h-4 w-3/4" />
                                            <LemonSkeleton className="h-3 w-1/2" />
                                        </div>
                                    ))}
                                </div>
                            ) : sortedPRs.length === 0 ? (
                                <div className="p-6 text-center text-sm text-secondary">No open pull requests</div>
                            ) : (
                                sortedPRs.map((pr) => (
                                    <PRListItem
                                        key={pr.number}
                                        pr={pr}
                                        owner={owner}
                                        name={name}
                                        selected={number === pr.number}
                                    />
                                ))
                            )}
                        </div>
                    </aside>
                )}

                {/* Workspace column */}
                <section className="flex-1 min-w-0">
                    {number ? (
                        <GitHogPRWorkspace owner={owner} name={name} number={number} />
                    ) : (
                        <div className="border-2 border-dashed border-border rounded-lg p-16 flex flex-col items-center gap-2 text-center">
                            <p className="text-secondary text-sm my-0">Select a pull request from the inbox</p>
                            <p className="text-muted text-xs my-0">
                                Risk scores load asynchronously and are cached after first computation
                            </p>
                        </div>
                    )}
                </section>
            </div>
        </SceneContent>
    )
}

export default GitHogRepoScene
