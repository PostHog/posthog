import { useValues } from 'kea'
import { useEffect, useMemo, useState } from 'react'

import { IconInfo, IconMagicWand, IconSparkles } from '@posthog/icons'
import { LemonButton, LemonSelect, LemonTag, Popover, Tooltip } from '@posthog/lemon-ui'

import { GitHubRepositoryPicker } from 'lib/integrations/GitHubIntegrationHelpers'
import { integrationsLogic } from 'lib/integrations/integrationsLogic'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'

export type FixWithAIStatus = 'idle' | 'in_progress' | 'done'

export function FixWithAIButton(): JSX.Element {
    const [isOpen, setIsOpen] = useState(false)
    const [status, setStatus] = useState<FixWithAIStatus>('idle')
    const prLink = useMemo(() => 'https://github.com/posthog/posthog/pull/42424', [])
    const [integrationId, setIntegrationId] = useState<number | undefined>(undefined)
    const [repository, setRepository] = useState<string>('')

    useEffect(() => {
        if (status === 'in_progress') {
            const timeout = setTimeout(() => setStatus('done'), 3000)
            return () => clearTimeout(timeout)
        }
    }, [status])

    return (
        <Popover
            visible={isOpen}
            onClickOutside={() => setIsOpen(false)}
            overlay={
                <FixWithAIPopoverContent
                    status={status}
                    setStatus={setStatus}
                    prLink={prLink}
                    integrationId={integrationId}
                    setIntegrationId={setIntegrationId}
                    repository={repository}
                    setRepository={setRepository}
                />
            }
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

export function FixWithAIPopoverContent({
    status,
    setStatus,
    prLink,
    integrationId,
    setIntegrationId,
    repository,
    setRepository,
}: {
    status: FixWithAIStatus
    setStatus: (s: FixWithAIStatus) => void
    prLink: string
    integrationId: number | undefined
    setIntegrationId: (id: number | undefined) => void
    repository: string
    setRepository: (repo: string) => void
}): JSX.Element {
    const isInProgress = status === 'in_progress'
    const isDone = status === 'done'
    const { getIntegrationsByKind } = useValues(integrationsLogic)
    const githubIntegrations = getIntegrationsByKind(['github'])

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
                            <GitHubRepositoryPicker
                                integrationId={integrationId}
                                value={repository}
                                onChange={(value) => setRepository(value || '')}
                                keepParentPopoverOpenOnClick={true}
                            />
                        </div>
                    )}
                </div>

                <div className="mt-3 flex items-center gap-2">
                    {!isDone ? (
                        <LemonButton
                            type="primary"
                            icon={<IconSparkles />}
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
                            {isInProgress ? 'In progress…' : 'Start fix'}
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
