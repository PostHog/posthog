import { useValues } from 'kea'
import { useEffect, useMemo, useState } from 'react'

import { IconExternal, IconGithub, IconMagicWand, IconPencil, IconSparkles } from '@posthog/icons'
import { LemonButton, LemonTag, Tooltip } from '@posthog/lemon-ui'

import { GitHubRepositoryPicker } from 'lib/integrations/GitHubIntegrationHelpers'
import { integrationsLogic } from 'lib/integrations/integrationsLogic'
import { Link } from 'lib/lemon-ui/Link'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'

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
        if (release?.metadata?.git?.repo_name) {
            setRepository(release.metadata.git.repo_name)
        }
    }, [release])

    const handleStartFix = (): void => {
        if (!integrationId || !repository) {
            setShowRepositoryPicker(true)
            return
        }
        setStatus('in_progress')
        // TODO: Implement actual AI fix logic here
        setTimeout(() => setStatus('done'), 3000) // Mock progress
    }

    const isInProgress = status === 'in_progress'
    const isDone = status === 'done'

    return (
        <div className="border border-border rounded-lg overflow-hidden">
            {/* Header */}
            <div className="bg-bg-3000 px-3 py-2 border-b border-border">
                <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                        <IconSparkles className="text-lg" />
                        <span className="font-semibold text-sm">AI Assistant</span>
                    </div>
                    <LemonTag size="small" type="danger">
                        Experimental
                    </LemonTag>
                </div>
            </div>

            {/* Content */}
            <div className="p-3 space-y-3">
                {/* Repository Selection */}
                {repository && !showRepositoryPicker ? (
                    <div className="flex items-center justify-between p-2 bg-bg-3000 rounded-lg">
                        <Tooltip title={`Repository: ${repository}`}>
                            <div className="flex items-center gap-2 text-sm">
                                <IconGithub className="text-muted-alt" />
                                <span className="text-default font-medium truncate max-w-[150px]">
                                    {repository.split('/').pop()}
                                </span>
                            </div>
                        </Tooltip>
                        <ButtonPrimitive
                            size="xxs"
                            onClick={() => setShowRepositoryPicker(true)}
                            tooltip="Change repository"
                        >
                            <IconPencil className="text-xs" />
                        </ButtonPrimitive>
                    </div>
                ) : null}

                {/* Repository Picker */}
                {showRepositoryPicker && integrationId && (
                    <div className="space-y-2">
                        <label className="text-xs font-medium text-muted-alt">Select repository</label>
                        <GitHubRepositoryPicker
                            integrationId={integrationId}
                            value={repository}
                            onChange={(repo: string) => {
                                setRepository(repo)
                                setShowRepositoryPicker(false)
                            }}
                        />
                        {repository && (
                            <ButtonPrimitive
                                size="xxs"
                                variant="outline"
                                onClick={() => setShowRepositoryPicker(false)}
                            >
                                Cancel
                            </ButtonPrimitive>
                        )}
                    </div>
                )}

                {/* Main Fix Button */}
                {!showRepositoryPicker && (
                    <LemonButton
                        type="primary"
                        fullWidth
                        icon={<IconMagicWand />}
                        onClick={handleStartFix}
                        loading={isInProgress}
                        disabled={isDone}
                    >
                        {isInProgress ? 'Generating fix...' : isDone ? 'Fix generated' : 'Fix with AI'}
                    </LemonButton>
                )}

                {/* Pull Requests Section */}
                {pullRequests.length > 0 && (
                    <div className="space-y-2">
                        <div className="flex items-center gap-1">
                            <span className="text-xs font-medium text-muted-alt">Related Pull Requests</span>
                            <span className="text-xs text-muted-alt">({pullRequests.length})</span>
                        </div>

                        <div className="space-y-1">
                            {pullRequests.map((pr) => (
                                <Link key={pr.id} to={pr.url} target="_blank">
                                    <ButtonPrimitive
                                        fullWidth
                                        variant="outline"
                                        size="xxs"
                                        className="justify-start text-left"
                                    >
                                        <div className="flex items-center gap-2 w-full">
                                            <IconExternal className="text-muted-alt flex-shrink-0" />
                                            <div className="flex-1 min-w-0">
                                                <div className="truncate text-xs">{pr.title}</div>
                                                <div className="flex items-center gap-2 mt-0.5">
                                                    <span
                                                        className={`text-[10px] font-medium ${
                                                            pr.status === 'open'
                                                                ? 'text-success'
                                                                : pr.status === 'merged'
                                                                  ? 'text-purple'
                                                                  : 'text-muted-alt'
                                                        }`}
                                                    >
                                                        {pr.status.toUpperCase()}
                                                    </span>
                                                    <span className="text-[10px] text-muted-alt">
                                                        #{pr.url.split('/').pop()}
                                                    </span>
                                                </div>
                                            </div>
                                        </div>
                                    </ButtonPrimitive>
                                </Link>
                            ))}
                        </div>
                    </div>
                )}
            </div>
        </div>
    )
}
