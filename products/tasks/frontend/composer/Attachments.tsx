import { JSX, useEffect, useRef, useState } from 'react'

import { IconDocument, IconPlus, IconX } from '@posthog/icons'
import { LemonButton, Tooltip } from '@posthog/lemon-ui'

const IMAGE_TYPES = /^image\//

function isImage(file: File): boolean {
    return IMAGE_TYPES.test(file.type)
}

function FileThumbnail({ file }: { file: File }): JSX.Element {
    const [url, setUrl] = useState<string | null>(null)
    useEffect(() => {
        if (!isImage(file)) {
            return
        }
        const objectUrl = URL.createObjectURL(file)
        setUrl(objectUrl)
        return () => URL.revokeObjectURL(objectUrl)
    }, [file])

    if (url) {
        return <img src={url} alt={file.name} className="h-8 w-8 rounded object-cover" />
    }
    return (
        <div className="flex h-8 w-8 items-center justify-center rounded bg-fill-highlight-100">
            <IconDocument className="text-muted" />
        </div>
    )
}

export function AttachmentsBar({
    files,
    onRemove,
}: {
    files: File[]
    onRemove: (index: number) => void
}): JSX.Element | null {
    if (files.length === 0) {
        return null
    }
    return (
        <div className="flex flex-wrap gap-2 px-2 pt-2">
            {files.map((file, index) => (
                <div
                    key={`${file.name}-${index}`}
                    className="flex items-center gap-2 rounded border border-border bg-bg-light py-1 pl-1 pr-2"
                >
                    <FileThumbnail file={file} />
                    <span className="max-w-[160px] truncate text-xs" title={file.name}>
                        {file.name}
                    </span>
                    <LemonButton
                        size="xsmall"
                        icon={<IconX />}
                        onClick={() => onRemove(index)}
                        tooltip="Remove attachment"
                        aria-label={`Remove ${file.name}`}
                    />
                </div>
            ))}
        </div>
    )
}

export function AttachmentButton({
    onAddFiles,
    disabled,
}: {
    onAddFiles: (files: File[]) => void
    disabled?: boolean
}): JSX.Element {
    const inputRef = useRef<HTMLInputElement>(null)

    return (
        <>
            <input
                ref={inputRef}
                type="file"
                multiple
                accept="image/*,.pdf,.txt,.md,.csv,.json,.log,.yaml,.yml,.html,.css,.js,.ts,.tsx,.jsx,.py"
                className="hidden"
                onChange={(event) => {
                    const selected = Array.from(event.target.files ?? [])
                    if (selected.length > 0) {
                        onAddFiles(selected)
                    }
                    event.target.value = ''
                }}
            />
            <Tooltip title="Attach files">
                <LemonButton
                    size="xsmall"
                    type="tertiary"
                    icon={<IconPlus />}
                    disabled={disabled}
                    onClick={() => inputRef.current?.click()}
                    aria-label="Attach files"
                />
            </Tooltip>
        </>
    )
}
