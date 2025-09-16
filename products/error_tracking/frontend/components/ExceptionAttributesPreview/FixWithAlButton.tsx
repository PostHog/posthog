import { useValues } from 'kea'
import { useEffect, useMemo, useState } from 'react'

import { IconInfo, IconMagicWand } from '@posthog/icons'
import { LemonButton, LemonSelect, LemonTag, Popover, Tooltip } from '@posthog/lemon-ui'

import { GitHubRepositoryPicker, useRepositories } from 'lib/integrations/GitHubIntegrationHelpers'
import { integrationsLogic } from 'lib/integrations/integrationsLogic'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'

import { releasePreviewLogic } from './ReleasesPreview/releasePreviewLogic'

export type FixWithAIStatus = 'idle' | 'in_progress' | 'done'

export function FixWithAIButton(): JSX.Element {
    const [isOpen, setIsOpen] = useState(false)

    return (
        <Popover
            visible={isOpen}
            onClickOutside={() => setIsOpen(false)}
            overlay={<FixWithAIPopoverContent />}
            placement="bottom-end"
            padded={false}
            showArrow
        >
            <span>
                <ButtonPrimitive
                    onClick={() => setIsOpen((v) => !v)}
                    className="px-2 h-[1.4rem]"
                    tooltip="Generate AI prompt to fix this error"
                >
                    <IconMagicWand />
                    Fix with AI
                    <LemonTag size="small" type="danger">
                        Experimental
                    </LemonTag>
                </ButtonPrimitive>
            </span>
        </Popover>
    )
}

export function FixWithAIPopoverContent(): JSX.Element {
    const { getIntegrationsByKind } = useValues(integrationsLogic)
    const githubIntegrations = getIntegrationsByKind(['github'])
    const [integrationId, setIntegrationId] = useState<number | undefined>(undefined)

    const [status, setStatus] = useState<FixWithAIStatus>('idle')
    const [repository, setRepository] = useState<string>('')
    const prLink = useMemo(() => 'https://github.com/posthog/posthog/pull/42424', [])
    const isInProgress = status === 'in_progress'
    const isDone = status === 'done'

    useEffect(() => {
        if (!integrationId && githubIntegrations.length === 1) {
            setIntegrationId(githubIntegrations[0].id as number)
        }
    }, [githubIntegrations, integrationId])

    return (
        <div className="overflow-hidden min-w-[320px]">
            <div className="border-b-1 p-2 flex items-center justify-between gap-3">
                <h4 className="mb-0">Fix with AI</h4>
                <Tooltip title="Our agent will attempt to reproduce and fix this issue, open a PR with the changes, and share a link here.">
                    <IconInfo className="text-muted-alt" />
                </Tooltip>
            </div>
            <div className="p-2">
                <div className="space-y-2">
                    <div>
                        <label className="block text-sm font-medium mb-1">GitHub Integration</label>
                        <LemonSelect
                            value={integrationId}
                            onChange={(id) => {
                                setIntegrationId(id as number | undefined)
                                setRepository('')
                            }}
                            options={githubIntegrations.map((integration: any) => ({
                                value: integration.id,
                                label: `${integration.display_name} (${integration.config?.account?.name || 'GitHub'})`,
                            }))}
                            placeholder="Select GitHub integration..."
                            fullWidth
                        />
                    </div>

                    {integrationId != null && (
                        <div>
                            <label className="block text-sm font-medium mb-1">Repository</label>
                            <RepositoryPicker integrationId={integrationId} />
                        </div>
                    )}
                </div>

                <div className="mt-3 flex items-center gap-2 justify-end">
                    {!isDone ? (
                        <LemonButton
                            type="primary"
                            icon={<IconMagicWand />}
                            onClick={() => {
                                setStatus('in_progress')
                            }}
                            disabled={isInProgress || !integrationId || !repository}
                            disabledReason={
                                isInProgress
                                    ? undefined
                                    : !integrationId
                                      ? 'Select GitHub integration'
                                      : !repository
                                        ? 'Select repository'
                                        : undefined
                            }
                        >
                            {isInProgress ? 'In progress…' : 'Start'}
                        </LemonButton>
                    ) : (
                        <LemonButton type="primary" to={prLink} targetBlank>
                            Open PR
                        </LemonButton>
                    )}
                </div>
            </div>
        </div>
    )
}

function RepositoryPicker({ integrationId }: { integrationId: number }): JSX.Element {
    const { release } = useValues(releasePreviewLogic)
    const { options } = useRepositories(integrationId)

    const [repository, setRepository] = useState<string>('')

    useEffect(() => {
        if (
            release &&
            release.metadata?.git?.repo_name &&
            options.some((option) => option.key === release.metadata?.git?.repo_name)
        ) {
            setRepository(release.metadata?.git?.repo_name)
        }
    }, [options, release])

    return (
        <GitHubRepositoryPicker
            integrationId={integrationId}
            value={repository}
            onChange={() => {}}
            keepParentPopoverOpenOnClick
        />
    )
}
