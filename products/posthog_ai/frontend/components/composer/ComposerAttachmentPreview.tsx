import { useEffect, useState } from 'react'

import { IconDocument, IconImage } from '@posthog/icons'

import { getFileExtension, isImageAttachment } from '../../utils/attachments'

export function ComposerAttachmentPreview({ file }: { file: File }): JSX.Element {
    const [src, setSrc] = useState<string | null>(null)
    const isImage = isImageAttachment(file.name)

    useEffect(() => {
        if (!isImage) {
            return
        }
        const objectUrl = URL.createObjectURL(file)
        setSrc(objectUrl)
        return () => URL.revokeObjectURL(objectUrl)
    }, [file, isImage])

    if (isImage) {
        return src ? <img src={src} alt="" className="size-full object-cover" /> : <IconImage />
    }

    const extension = getFileExtension(file.name)
    return extension && extension.length <= 5 ? (
        <span className="text-xxs font-medium uppercase">{extension === 'json' ? '{}' : extension}</span>
    ) : (
        <IconDocument />
    )
}
