import { IconEllipsis } from '@posthog/icons'
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
    templateChanged,
    saving,
    onSendTest,
    onDiscard,
    onSave,
    onSaveAsNew,
    onDuplicate,
    onDelete,
}: {
    isNew: boolean
    sendTestDisabledReason?: string
    saveDisabledReason?: string
    duplicateDisabledReason?: string
    templateChanged: boolean
    saving: boolean
    onSendTest: () => void
    onDiscard: () => void
    onSave: () => void
    onSaveAsNew: () => void
    onDuplicate: () => void
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
                    <DropdownMenuItem data-attr="save-as-new-template" onClick={onSaveAsNew}>
                        Save as new template
                    </DropdownMenuItem>
                    {!isNew && (
                        <>
                            <DropdownMenuItem
                                data-attr="duplicate-message-template"
                                disabledReason={duplicateDisabledReason}
                                onClick={onDuplicate}
                            >
                                Duplicate
                            </DropdownMenuItem>
                            <DropdownMenuSeparator />
                            <DropdownMenuItem
                                data-attr="delete-message-template"
                                variant="destructive"
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
