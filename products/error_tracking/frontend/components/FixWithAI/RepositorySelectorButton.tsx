import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { IconGitRepository } from '@posthog/icons'
import { LemonSelect, Popover } from '@posthog/lemon-ui'

import { GitHubRepositoryPicker, useRepositories } from 'lib/integrations/GitHubIntegrationHelpers'
import { integrationsLogic } from 'lib/integrations/integrationsLogic'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'

import { releasePreviewLogic } from '../ExceptionAttributesPreview/ReleasesPreview/releasePreviewLogic'
import { fixWithAiLogic } from './fixWithAiLogic'

export function RepositorySelectorButton(): JSX.Element {
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
            {integrationId && <DefaultRepositoryPicker integrationId={integrationId} />}
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
                    <IconGitRepository className="flex-shrink-0" />
                    <span className="truncate font-medium">
                        {repository ? repository.split('/').pop() : 'Select repository...'}
                    </span>
                </ButtonPrimitive>
            </Popover>
        </>
    )
}

function RepositoryPickerPopover(): JSX.Element {
    const { getIntegrationsByKind } = useValues(integrationsLogic)
    const githubIntegrations = getIntegrationsByKind(['github'])

    const { integrationId, repository } = useValues(fixWithAiLogic)
    const { setRepository, setIntegrationId, setRepositoryPopoverVisible } = useActions(fixWithAiLogic)

    const handleIntegrationChange = (id: number | undefined): void => {
        if (!id) {
            return
        }

        setIntegrationId(id)
        setRepository('')
    }

    const handleRepositoryChange = (repo: string): void => {
        setRepository(repo)
        setRepositoryPopoverVisible(false)
    }

    return (
        <div className="flex flex-col gap-3 p-3 min-w-[300px]">
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
                    <GitHubRepositoryPicker
                        integrationId={integrationId!}
                        value={repository ?? ''}
                        onChange={handleRepositoryChange}
                        keepParentPopoverOpenOnClick
                    />
                </div>
            )}
        </div>
    )
}

function DefaultRepositoryPicker({ integrationId }: { integrationId: number }): JSX.Element {
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
