import { useActions, useValues } from 'kea'
import { useEffect, useRef, useState } from 'react'

import { IconUpload } from '@posthog/icons'
import { LemonButton, LemonInput, Spinner } from '@posthog/lemon-ui'

import { LemonModal } from 'lib/lemon-ui/LemonModal'
import { LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { teamLogic } from 'scenes/teamLogic'

import { emailMediaLibraryLogic, uploadEmailImage, uploadErrorText } from '../emailMediaLibraryLogic'

export interface PickedEmailImage {
    src: string
    alt?: string
    naturalWidth?: number | null
    naturalHeight?: number | null
    mediaId?: string
}

type PickerTab = 'upload' | 'library' | 'link'

export function EmailImagePickerModal({
    isOpen,
    onClose,
    onAfterClose,
    onPick,
}: {
    isOpen: boolean
    onClose: () => void
    /** The modal gives focus back to whatever opened it, so the editor can only take it after that. */
    onAfterClose: () => void
    onPick: (image: PickedEmailImage) => void
}): JSX.Element {
    const { currentProjectId } = useValues(teamLogic)
    const { images, imagesLoading, search, hasMoreImages } = useValues(emailMediaLibraryLogic)
    const { loadImages, loadMoreImages, setSearch } = useActions(emailMediaLibraryLogic)
    const [tab, setTab] = useState<PickerTab>('upload')
    const [uploading, setUploading] = useState(false)
    const [error, setError] = useState<string | null>(null)
    const [url, setUrl] = useState('')
    const inputRef = useRef<HTMLInputElement>(null)
    // Bumped whenever the picker opens, closes or goes away, so an upload that finishes after that is ignored.
    const session = useRef(0)

    useEffect(() => {
        session.current += 1
        return () => {
            session.current += 1
        }
    }, [isOpen])

    useEffect(() => {
        if (isOpen) {
            setTab('upload')
            setError(null)
            setUrl('')
        }
    }, [isOpen])

    useEffect(() => {
        if (isOpen && tab === 'library') {
            loadImages()
        }
    }, [isOpen, tab, loadImages])

    const upload = async (file: File | undefined): Promise<void> => {
        if (!file) {
            return
        }
        if (!file.type.startsWith('image/')) {
            setError('That file is not an image. Choose a PNG, JPEG or GIF.')
            return
        }
        const uploadSession = session.current
        setUploading(true)
        setError(null)
        try {
            const media = await uploadEmailImage(String(currentProjectId), file)
            if (session.current !== uploadSession) {
                return
            }
            onPick({
                src: media.image_location,
                alt: '',
                naturalWidth: media.width ?? null,
                naturalHeight: media.height ?? null,
                mediaId: media.id,
            })
        } catch (uploadError) {
            setError(uploadErrorText(uploadError))
        } finally {
            setUploading(false)
        }
    }

    const urlIsValid = /^(https?:\/\/\S+|\{\{[\s\S]+\}\})$/i.test(url.trim())
    const addFromLink = (): void => {
        if (urlIsValid) {
            // A replaced image's size belongs to the old picture, and the new one is measured once it loads.
            onPick({ src: url.trim(), alt: '', naturalWidth: null, naturalHeight: null })
        }
    }

    return (
        <LemonModal isOpen={isOpen} onClose={onClose} onAfterClose={onAfterClose} title="Add image" width={640}>
            <LemonTabs
                activeKey={tab}
                onChange={setTab}
                tabs={[
                    {
                        key: 'upload',
                        label: 'Upload',
                        content: (
                            <div
                                className="flex flex-col gap-2 items-center justify-center border border-dashed rounded p-8"
                                data-attr="email-editor-image-dropzone"
                                onDragOver={(event) => event.preventDefault()}
                                onDrop={(event) => {
                                    event.preventDefault()
                                    void upload(event.dataTransfer.files[0])
                                }}
                            >
                                <input
                                    ref={inputRef}
                                    type="file"
                                    accept="image/*"
                                    className="hidden"
                                    data-attr="email-editor-image-file"
                                    onChange={(event) => {
                                        void upload(event.target.files?.[0])
                                        event.target.value = ''
                                    }}
                                />
                                <LemonButton
                                    type="primary"
                                    icon={<IconUpload />}
                                    loading={uploading}
                                    onClick={() => inputRef.current?.click()}
                                >
                                    Choose an image
                                </LemonButton>
                                <span className="text-secondary text-xs">
                                    Or drop one here. Images over 4 MB are resized for you.
                                </span>
                                {error ? <span className="text-danger text-xs">{error}</span> : null}
                            </div>
                        ),
                    },
                    {
                        key: 'library',
                        label: 'Your images',
                        content: (
                            <div className="flex flex-col gap-2">
                                <LemonInput
                                    type="search"
                                    placeholder="Search your images"
                                    value={search}
                                    onChange={setSearch}
                                    data-attr="email-editor-image-search"
                                />
                                {imagesLoading && images === null ? (
                                    <div className="flex justify-center p-8">
                                        <Spinner className="text-2xl" />
                                    </div>
                                ) : images?.length ? (
                                    <div className="grid grid-cols-3 gap-2 max-h-96 overflow-y-auto">
                                        {images.map((media) => (
                                            <button
                                                key={media.id}
                                                type="button"
                                                className="border rounded overflow-hidden cursor-pointer h-28 bg-surface-secondary"
                                                data-attr="email-editor-image-library-item"
                                                title={media.name}
                                                onClick={() =>
                                                    onPick({
                                                        src: media.url,
                                                        alt: '',
                                                        naturalWidth: media.width ?? null,
                                                        naturalHeight: media.height ?? null,
                                                        mediaId: media.id,
                                                    })
                                                }
                                            >
                                                <img
                                                    src={media.url}
                                                    alt={media.name}
                                                    className="w-full h-full object-contain"
                                                />
                                            </button>
                                        ))}
                                        {hasMoreImages ? (
                                            <LemonButton
                                                type="secondary"
                                                center
                                                className="col-span-3"
                                                loading={imagesLoading}
                                                onClick={() => loadMoreImages()}
                                                data-attr="email-editor-image-library-more"
                                            >
                                                Show more images
                                            </LemonButton>
                                        ) : null}
                                    </div>
                                ) : (
                                    <p className="text-secondary m-0 p-4 text-center">
                                        {search
                                            ? 'No images match. Try another search.'
                                            : 'No images yet. Upload one and every template can use it.'}
                                    </p>
                                )}
                            </div>
                        ),
                    },
                    {
                        key: 'link',
                        label: 'From a link',
                        content: (
                            <div
                                className="flex gap-2"
                                onKeyDown={(event) => {
                                    if (event.key === 'Enter') {
                                        event.preventDefault()
                                        addFromLink()
                                    }
                                }}
                            >
                                <LemonInput
                                    className="flex-1"
                                    placeholder="https://example.com/image.png"
                                    value={url}
                                    onChange={setUrl}
                                    autoFocus
                                    data-attr="email-editor-image-url"
                                />
                                <LemonButton
                                    type="primary"
                                    onClick={addFromLink}
                                    disabledReason={
                                        urlIsValid ? undefined : 'Enter a full link, starting with https://'
                                    }
                                >
                                    Add image
                                </LemonButton>
                            </div>
                        ),
                    },
                ]}
            />
        </LemonModal>
    )
}
