import type { RefObject } from 'react'

import { IconPlus } from '@posthog/icons'
import { Button, Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill-primitives'

import { useComposerFilePicker } from '../composer/useComposerFilePicker'

export interface QuillComposerAttachButtonProps {
    attachmentsKey: string
    dropTargetRef?: RefObject<HTMLElement>
    disabledReason?: string
}

export function QuillComposerAttachButton({
    attachmentsKey,
    dropTargetRef,
    disabledReason,
}: QuillComposerAttachButtonProps): JSX.Element {
    const { fileInput, openPicker, isOver, addDisabledReason } = useComposerFilePicker(
        attachmentsKey,
        dropTargetRef,
        disabledReason
    )
    return (
        <>
            {fileInput}
            <Tooltip>
                <TooltipTrigger
                    render={
                        <Button
                            variant="default"
                            size="icon-sm"
                            aria-label="Attach files"
                            disabled={!!addDisabledReason}
                            onClick={openPicker}
                            className={isOver ? 'ring-1 ring-ring' : undefined}
                            data-attr="posthog-ai-attach-file"
                        >
                            <IconPlus />
                        </Button>
                    }
                />
                <TooltipContent>
                    {addDisabledReason ?? (isOver ? 'Drop to attach' : 'Attach files for PostHog AI to read')}
                </TooltipContent>
            </Tooltip>
        </>
    )
}
