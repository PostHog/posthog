import { useActions, useValues } from 'kea'
import { useEffect, useMemo, useState } from 'react'

import { IconExternal, IconGitRepository, IconMagicWand } from '@posthog/icons'
import { LemonButton, LemonSelect, Popover } from '@posthog/lemon-ui'

import { GitHubRepositoryPicker, useRepositories } from 'lib/integrations/GitHubIntegrationHelpers'
import { integrationsLogic } from 'lib/integrations/integrationsLogic'
import { Link } from 'lib/lemon-ui/Link'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'

import { releasePreviewLogic } from '../ExceptionAttributesPreview/ReleasesPreview/releasePreviewLogic'
import { fixWithAiLogic } from './fixWithAiLogic'

export type FixWithAIStatus = 'idle' | 'in_progress' | 'done'

interface PullRequest {
    id: number
    title: string
    url: string
    status: 'open' | 'merged' | 'closed'
}

export function IssueAIFix(): JSX.Element {
    const [showPRsPopover, setShowPRsPopover] = useState(false)
    const { integrationId, repository, fixStatus } = useValues(fixWithAiLogic)
    const { generateFix } = useActions(fixWithAiLogic)

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

    const isInProgress = fixStatus === 'in_progress'
    const isDone = fixStatus === 'done'

    return (
        <div className="space-y-3">
            <div className="flex gap-2 items-stretch">
                <RepositorySelectorButton />
                <LemonButton
                    type="primary"
                    icon={<IconMagicWand />}
                    onClick={generateFix}
                    loading={isInProgress}
                    disabled={isDone || !repository || !integrationId}
                    disabledReason={
                        !integrationId
                            ? 'No GitHub integration configured'
                            : !repository
                              ? 'Select a repository first'
                              : undefined
                    }
                    className="flex-shrink-0"
                >
                    {isInProgress ? 'Generating fix...' : isDone ? 'Fix generated' : 'Fix with AI'}
                </LemonButton>
            </div>

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

function RepositorySelectorButton(): JSX.Element {
    const { repository, repositoryPopoverVisible, integrationId } = useValues(fixWithAiLogic)
    const { setRepositoryPopoverVisible, setIntegrationId } = useActions(fixWithAiLogic)

    const { getIntegrationsByKind } = useValues(integrationsLogic)
    const githubIntegrations = getIntegrationsByKind(['github'])

    useEffect(() => {
        if (githubIntegrations.length === 1) {
            setIntegrationId(githubIntegrations[0].id)
        }
    }, [githubIntegrations, setIntegrationId])

    return (
        <>
            {integrationId && <ShadowRepositoryPicker integrationId={integrationId} />}
            <Popover
                visible={repositoryPopoverVisible}
                onClickOutside={() => setRepositoryPopoverVisible(false)}
                overlay={<RepositoryPickerPopover />}
                placement="bottom-start"
                showArrow
            >
                <ButtonPrimitive
                    variant="outline"
                    size="fit"
                    onClick={() => setRepositoryPopoverVisible(true)}
                    className="px-3 min-w-0 flex-1"
                    tooltip="Click to select repository"
                >
                    <IconGitRepository className="text-muted-alt flex-shrink-0" />
                    <span className="truncate font-medium">
                        {repository ? repository.split('/').pop() : 'Select repository...'}
                    </span>
                </ButtonPrimitive>
            </Popover>
        </>
    )
}

function ShadowRepositoryPicker({ integrationId }: { integrationId: number }): JSX.Element {
    const { options } = useRepositories(integrationId)
    const { setRepository } = useActions(fixWithAiLogic)
    const { release } = useValues(releasePreviewLogic)

    useEffect(() => {
        if (!options || !release?.metadata?.git?.repo_name) {
            return
        }

        if (options.some((option) => option.key === release.metadata?.git?.repo_name)) {
            setRepository(release.metadata.git.repo_name)
        }
    }, [options, release, setRepository])

    return <></>
}

function RepositoryPickerPopover(): JSX.Element {
    const { getIntegrationsByKind } = useValues(integrationsLogic)
    const githubIntegrations = getIntegrationsByKind(['github'])

    const { integrationId } = useValues(fixWithAiLogic)
    const { setRepository, setIntegrationId } = useActions(fixWithAiLogic)

    useEffect(() => {
        if (githubIntegrations.length === 1) {
            setIntegrationId(githubIntegrations[0].id)
        }
    }, [githubIntegrations.length, setIntegrationId, githubIntegrations])

    const handleIntegrationChange = (id: number | undefined): void => {
        if (!id) {
            return
        }

        setIntegrationId(id)
        setRepository('')
    }

    return (
        <div className="p-3 min-w-[300px]">
            <div className="space-y-3">
                <div>
                    <label className="block text-sm font-medium mb-1">GitHub Integration</label>
                    <LemonSelect
                        value={integrationId}
                        onChange={handleIntegrationChange}
                        options={githubIntegrations.map((integration: any) => ({
                            value: integration.id,
                            label: `${integration.display_name} (${integration.config?.account?.name || 'GitHub'})`,
                        }))}
                        placeholder="Select GitHub integration..."
                        fullWidth
                    />
                </div>

                {integrationId && (
                    <div>
                        <label className="block text-sm font-medium mb-1">Repository</label>
                        <RepositoryPicker />
                    </div>
                )}
            </div>
        </div>
    )
}

function RepositoryPicker(): JSX.Element {
    const { repository, integrationId } = useValues(fixWithAiLogic)

    const { setRepository, setRepositoryPopoverVisible } = useActions(fixWithAiLogic)

    const setRepositoryAndClosePopover = (repo: string): void => {
        setRepository(repo)
        setRepositoryPopoverVisible(false)
    }

    return (
        <GitHubRepositoryPicker
            integrationId={integrationId!}
            value={repository ?? ''}
            onChange={setRepositoryAndClosePopover}
            keepParentPopoverOpenOnClick
        />
    )
}
