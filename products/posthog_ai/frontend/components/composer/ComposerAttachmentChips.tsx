import { useActions, useValues } from 'kea'

import { useThreadSkin } from '../../hooks/useThreadSkin'
import { composerAttachmentsLogic } from '../../logics/composerAttachmentsLogic'
import { QuillComposerAttachment } from '../quill/QuillComposerAttachment'
import { ComposerAttachment } from './ComposerAttachment'

export function ComposerAttachmentChips({ attachmentsKey }: { attachmentsKey: string }): JSX.Element | null {
    const logic = composerAttachmentsLogic({ attachmentsKey })
    const { stagedAttachments, uploading } = useValues(logic)
    const { removeAttachment } = useActions(logic)
    const skin = useThreadSkin()
    const Attachment = skin === 'quill' ? QuillComposerAttachment : ComposerAttachment
    if (stagedAttachments.length === 0) {
        return null
    }
    return (
        <>
            {stagedAttachments.map(({ id, file }) => (
                <Attachment key={id} file={file} uploading={uploading} onRemove={() => removeAttachment(id)} />
            ))}
        </>
    )
}
