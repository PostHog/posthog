import { useActions, useValues } from 'kea'
import type { RefObject } from 'react'

import { IconAtSign, IconGithub, IconPlus, IconUpload } from '@posthog/icons'
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
import { cn } from 'lib/utils/css-classes'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'

import { useComposerFilePicker } from '../../../components/composer/useComposerFilePicker'
import { COMPOSER_MENU_CLASS } from '../../../components/quill/composerMenuClass'
import { githubAuthorizeUrl } from './githubAuthorizeUrl'

export interface TaskComposerAddMenuProps {
    attachmentsKey: string
    dropTargetRef?: RefObject<HTMLElement>
    onAddRepository?: () => void
    onAddContext?: () => void
}

export function TaskComposerAddMenu({
    attachmentsKey,
    dropTargetRef,
    onAddRepository,
    onAddContext,
}: TaskComposerAddMenuProps): JSX.Element {
    const { fileInput, openPicker, isOver, addDisabledReason } = useComposerFilePicker(attachmentsKey, dropTargetRef)
    const { getIntegrationsByKind, integrationsLoading } = useValues(integrationsLogic)
    const { reportIntegrationConnectClicked } = useActions(eventUsageLogic)
    const needsGitHub = getIntegrationsByKind(['github']).length === 0
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
                                        aria-label="Add files, context or a repository"
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
                        {addDisabledReason ?? (isOver ? 'Drop to attach' : 'Add files, context or a repository')}
                    </TooltipContent>
                </Tooltip>
                <DropdownMenuContent
                    align="start"
                    side="top"
                    sideOffset={6}
                    className={cn('min-w-fit', COMPOSER_MENU_CLASS)}
                >
                    <DropdownMenuItem
                        disabled={!!addDisabledReason}
                        onClick={openPicker}
                        data-attr="posthog-ai-attach-file"
                    >
                        <IconUpload />
                        Attach files
                    </DropdownMenuItem>
                    {onAddContext && (
                        <DropdownMenuItem onClick={onAddContext} data-attr="posthog-ai-context-picker">
                            <IconAtSign />
                            Add context
                        </DropdownMenuItem>
                    )}
                    {onAddRepository &&
                        !integrationsLoading &&
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
