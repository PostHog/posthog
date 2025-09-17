import { useValues } from 'kea'
import { useEffect, useMemo, useState } from 'react'

import { IconExternal, IconGitRepository, IconMagicWand } from '@posthog/icons'
import { LemonButton, LemonTag, Popover } from '@posthog/lemon-ui'

import { GitHubRepositoryPicker } from 'lib/integrations/GitHubIntegrationHelpers'
import { integrationsLogic } from 'lib/integrations/integrationsLogic'
import { Link } from 'lib/lemon-ui/Link'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { Label } from 'lib/ui/Label/Label'

import { releasePreviewLogic } from '../ExceptionAttributesPreview/ReleasesPreview/releasePreviewLogic'

export type FixWithAIStatus = 'idle' | 'in_progress' | 'done'

interface PullRequest {
    id: number
    title: string
    url: string
    status: 'open' | 'merged' | 'closed'
}

export function IssueAIFix(): JSX.Element {
    const [status, setStatus] = useState<FixWithAIStatus>('idle')
    const [showRepositoryPicker, setShowRepositoryPicker] = useState(false)
    const [showPRsPopover, setShowPRsPopover] = useState(false)
    const { release } = useValues(releasePreviewLogic)
    const { getIntegrationsByKind } = useValues(integrationsLogic)
    const githubIntegrations = getIntegrationsByKind(['github'])
    const [integrationId, setIntegrationId] = useState<number | undefined>(undefined)
    const [repository, setRepository] = useState<string>('')

    // Mock pull requests - replace with actual data when available
    const pullRequests: PullRequest[] = useMemo(
        () => [
            {
                id: 1,
                title: 'Fix: Resolve null pointer exception in error handling',
                url: 'https://github.com/posthog/posthog/pull/42424',
                status: 'open',
            },
            {
                id: 2,
                title: 'Fix: Improve error boundary resilience',
                url: 'https://github.com/posthog/posthog/pull/42425',
                status: 'merged',
            },
        ],
        []
    )

    useEffect(() => {
        if (!integrationId && githubIntegrations.length === 1) {
            setIntegrationId(githubIntegrations[0].id as number)
        }
    }, [githubIntegrations, integrationId])

    useEffect(() => {
        // Auto-detect repository from release metadata
        if (release?.metadata?.git?.repo_name && !repository) {
            setRepository(release.metadata.git.repo_name)
        }
    }, [release, repository])

    const handleStartFix = (): void => {
        if (!integrationId || !repository) {
            return
        }
        setStatus('in_progress')
        // TODO: Implement actual AI fix logic here
        setTimeout(() => setStatus('done'), 3000) // Mock progress
    }

    const isInProgress = status === 'in_progress'
    const isDone = status === 'done'

    return (
        <div className="relative border border-border rounded-lg p-3 space-y-3 mt-2">
            {/* Label integrated into border */}
            <div className="absolute -top-2.5 -left-1 px-1 bg-bg-3000">
                <div className="flex items-center gap-2">
                    <Label intent="menu">AI Assistant</Label>
                    <LemonTag size="small" type="danger">
                        Experimental
                    </LemonTag>
                </div>
            </div>
            {/* Repository Selection and Fix Button on same line */}
            {integrationId ? (
                <div className="flex gap-2">
                    {!showRepositoryPicker ? (
                        <div className="flex gap-2 items-end w-full">
                            <ButtonPrimitive
                                variant="outline"
                                size="sm"
                                onClick={() => setShowRepositoryPicker(true)}
                                className="flex items-center gap-2 px-3 truncate flex-1"
                                tooltip="Click to change repository"
                            >
                                <IconGitRepository className="text-muted-alt" />
                                {repository ? (
                                    <span className="font-medium truncate">{repository.split('/').pop()}</span>
                                ) : (
                                    <span className="text-muted-alt">Select repository...</span>
                                )}
                            </ButtonPrimitive>
                            <LemonButton
                                type="primary"
                                icon={<IconMagicWand />}
                                onClick={handleStartFix}
                                loading={isInProgress}
                                disabled={isDone || !repository}
                                disabledReason={!repository ? 'Select a repository first' : undefined}
                            >
                                {isInProgress ? 'Generating fix...' : isDone ? 'Fix generated' : 'Fix with AI'}
                            </LemonButton>
                        </div>
                    ) : (
                        <div className="w-full space-y-2">
                            <label className="text-xs font-medium text-muted-alt">Select repository</label>
                            <GitHubRepositoryPicker
                                integrationId={integrationId}
                                value={repository}
                                onChange={(repo: string) => {
                                    setRepository(repo)
                                    setShowRepositoryPicker(false)
                                }}
                            />
                            <ButtonPrimitive
                                size="xxs"
                                variant="outline"
                                onClick={() => setShowRepositoryPicker(false)}
                            >
                                Cancel
                            </ButtonPrimitive>
                        </div>
                    )}
                </div>
            ) : (
                <div className="p-2 bg-bg-3000 rounded-lg text-center text-sm text-muted-alt">
                    No GitHub integration configured
                </div>
            )}

            {/* Pull Requests Popover */}
            {pullRequests.length > 0 && (
                <Popover
                    visible={showPRsPopover}
                    onClickOutside={() => setShowPRsPopover(false)}
                    overlay={
                        <div className="p-3 min-w-[320px] max-w-[400px]">
                            <div className="text-xs font-semibold text-default mb-2">Related Pull Requests</div>
                            <div className="space-y-1.5">
                                {pullRequests.map((pr) => (
                                    <Link key={pr.id} to={pr.url} target="_blank" className="block">
                                        <ButtonPrimitive
                                            fullWidth
                                            variant="outline"
                                            size="xxs"
                                            className="justify-between items-center px-2 py-1.5 hover:bg-bg-3000 transition-colors"
                                        >
                                            <div className="flex items-center gap-2 flex-1 min-w-0">
                                                <div
                                                    className={`w-1.5 h-1.5 rounded-full flex-shrink-0 ${
                                                        pr.status === 'open'
                                                            ? 'bg-success'
                                                            : pr.status === 'merged'
                                                              ? 'bg-purple'
                                                              : 'bg-muted-alt'
                                                    }`}
                                                />
                                                <span className="truncate text-xs font-medium text-default">
                                                    {pr.title}
                                                </span>
                                            </div>
                                            <div className="flex items-center gap-2 flex-shrink-0 ml-2">
                                                <span
                                                    className={`text-[10px] font-semibold uppercase ${
                                                        pr.status === 'open'
                                                            ? 'text-success'
                                                            : pr.status === 'merged'
                                                              ? 'text-purple'
                                                              : 'text-muted-alt'
                                                    }`}
                                                >
                                                    {pr.status}
                                                </span>
                                                <IconExternal className="text-muted-alt w-3 h-3" />
                                            </div>
                                        </ButtonPrimitive>
                                    </Link>
                                ))}
                            </div>
                        </div>
                    }
                    placement="top"
                    showArrow
                >
                    <div onMouseEnter={() => setShowPRsPopover(true)} onMouseLeave={() => setShowPRsPopover(false)}>
                        <ButtonPrimitive
                            variant="outline"
                            size="xxs"
                            className="text-xs text-muted-alt hover:text-default transition-colors"
                        >
                            See related pull requests ({pullRequests.length})
                        </ButtonPrimitive>
                    </div>
                </Popover>
            )}
        </div>
    )
}
