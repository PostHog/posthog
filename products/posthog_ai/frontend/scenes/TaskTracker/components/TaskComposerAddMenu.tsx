import { useActions, useValues } from 'kea'
import type { RefObject } from 'react'

import { IconGithub, IconPlus, IconUpload } from '@posthog/icons'
import {
    Button,
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuTrigger,
    Tooltip,
    TooltipContent,
    TooltipTrigger,
} from '@posthog/quill-primitives'

import { integrationsLogic } from 'lib/integrations/integrationsLogic'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'

import { useComposerFilePicker } from '../../../components/composer/useComposerFilePicker'
import { githubAuthorizeUrl } from './RepositorySelector'

export interface TaskComposerAddMenuProps {
    attachmentsKey: string
    dropTargetRef?: RefObject<HTMLElement>
    onAddRepository?: () => void
}

export function TaskComposerAddMenu({
    attachmentsKey,
    dropTargetRef,
    onAddRepository,
}: TaskComposerAddMenuProps): JSX.Element {
    const { fileInput, openPicker, isOver, addDisabledReason } = useComposerFilePicker(attachmentsKey, dropTargetRef)
    const { getIntegrationsByKind, integrationsLoading } = useValues(integrationsLogic)
    const { reportIntegrationConnectClicked } = useActions(eventUsageLogic)
    const needsGitHub = !integrationsLoading && getIntegrationsByKind(['github']).length === 0
    return (
        <>
            {fileInput}
            <DropdownMenu>
                <Tooltip>
                    <TooltipTrigger
                        render={
                            <DropdownMenuTrigger
                                render={
                                    <Button
                                        variant="default"
                                        size="icon-sm"
                                        aria-label="Add files or a repository"
                                        className={isOver ? 'ring-1 ring-ring' : undefined}
                                        data-attr="task-composer-add-menu"
                                    >
                                        <IconPlus />
                                    </Button>
                                }
                            />
                        }
                    />
                    <TooltipContent>
                        {addDisabledReason ?? (isOver ? 'Drop to attach' : 'Attach files or add a repository')}
                    </TooltipContent>
                </Tooltip>
                <DropdownMenuContent align="start" side="top" sideOffset={6} className="min-w-fit">
                    <DropdownMenuItem
                        disabled={!!addDisabledReason}
                        onClick={openPicker}
                        data-attr="posthog-ai-attach-file"
                    >
                        <IconUpload />
                        Attach files
                    </DropdownMenuItem>
                    {onAddRepository &&
                        (needsGitHub ? (
                            <DropdownMenuItem
                                render={<LinkPrimitive to={githubAuthorizeUrl} disableClientSideRouting />}
                                onClick={() => reportIntegrationConnectClicked('github', 'github', 'task_composer')}
                                data-attr="task-composer-connect-github"
                            >
                                <IconGithub />
                                Connect GitHub
                            </DropdownMenuItem>
                        ) : (
                            <DropdownMenuItem onClick={onAddRepository} data-attr="task-composer-add-repository">
                                <IconGithub />
                                Add a repository
                            </DropdownMenuItem>
                        ))}
                </DropdownMenuContent>
            </DropdownMenu>
        </>
    )
}
