import { IconEllipsis, IconUnlock } from '@posthog/icons'
import {
    Button,
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuSeparator,
    DropdownMenuTrigger,
    Separator,
} from '@posthog/quill'

export function QuillMessageTemplateActions({
    isNew,
    sendTestDisabledReason,
    saveDisabledReason,
    duplicateDisabledReason,
    releaseDisabledReason,
    deleteDisabledReason,
    templateChanged,
    saving,
    onSendTest,
    onDiscard,
    onSave,
    onSaveAsNew,
    onDuplicate,
    onRelease,
    onDelete,
}: {
    isNew: boolean
    sendTestDisabledReason?: string
    saveDisabledReason?: string
    duplicateDisabledReason?: string
    releaseDisabledReason?: string
    deleteDisabledReason?: string
    templateChanged: boolean
    saving: boolean
    onSendTest: () => void
    onDiscard: () => void
    onSave: () => void
    onSaveAsNew?: () => void
    onDuplicate: () => void
    onRelease?: () => void
    onDelete: () => void
}): JSX.Element {
    return (
        <>
            <Separator orientation="vertical" />
            <Button
                data-attr="send-test-message-template"
                variant="outline"
                onClick={onSendTest}
                disabledReason={sendTestDisabledReason}
            >
                Send test
            </Button>
            {templateChanged && (
                <Button data-attr="cancel-message-template" variant="outline" onClick={onDiscard}>
                    Discard changes
                </Button>
            )}
            <Button
                variant="primary"
                type="submit"
                form="template"
                onClick={onSave}
                loading={saving}
                disabledReason={saveDisabledReason}
            >
                {isNew ? 'Create' : 'Save'}
            </Button>
            <DropdownMenu>
                <DropdownMenuTrigger render={<Button size="icon" aria-label="More" tooltip="More" variant="default" />}>
                    <IconEllipsis />
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end">
                    {onSaveAsNew && (
                        <DropdownMenuItem data-attr="save-as-new-template" onClick={onSaveAsNew}>
                            Save as new template
                        </DropdownMenuItem>
                    )}
                    {!isNew && (
                        <>
                            <DropdownMenuItem
                                data-attr="duplicate-message-template"
                                disabledReason={duplicateDisabledReason}
                                onClick={onDuplicate}
                            >
                                Duplicate
                            </DropdownMenuItem>
                            {onRelease && (
                                <DropdownMenuItem
                                    data-attr="message-template-release"
                                    disabledReason={releaseDisabledReason}
                                    onClick={onRelease}
                                >
                                    <IconUnlock />
                                    Stop managing in code
                                </DropdownMenuItem>
                            )}
                            <DropdownMenuSeparator />
                            <DropdownMenuItem
                                data-attr="delete-message-template"
                                variant="destructive"
                                disabledReason={deleteDisabledReason}
                                onClick={onDelete}
                            >
                                Delete
                            </DropdownMenuItem>
                        </>
                    )}
                </DropdownMenuContent>
            </DropdownMenu>
        </>
    )
}
