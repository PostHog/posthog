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

import { useComposerFilePicker } from '../../../components/composer/useComposerFilePicker'

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
                    {onAddRepository && (
                        <DropdownMenuItem onClick={onAddRepository} data-attr="task-composer-add-repository">
                            <IconGithub />
                            Add a repository
                        </DropdownMenuItem>
                    )}
                </DropdownMenuContent>
            </DropdownMenu>
        </>
    )
}
