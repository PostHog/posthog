import { useEffect } from 'react'

import { IconTrash, IconUpload } from '@posthog/icons'
import { LemonButton, LemonFileInput, LemonInput, lemonToast } from '@posthog/lemon-ui'

import { useUploadFiles } from 'lib/hooks/useUploadFiles'

export interface EarlyAccessFeatureImageInputProps {
    id?: string
    value?: string
    onChange?: (value: string) => void
    onUploadingChange?: (uploading: boolean) => void
}

export function EarlyAccessFeatureImageInput({
    id,
    value,
    onChange,
    onUploadingChange,
}: EarlyAccessFeatureImageInputProps): JSX.Element {
    const { setFilesToUpload, filesToUpload, uploading } = useUploadFiles({
        onUpload: (url) => onChange?.(url),
        onError: (detail) => lemonToast.error(`Couldn't upload the image: ${detail}`),
    })

    useEffect(() => {
        onUploadingChange?.(uploading)
    }, [uploading, onUploadingChange])

    return (
        <div className="flex flex-col gap-2">
            {value ? (
                <div className="relative w-fit">
                    <img
                        src={value}
                        alt="Preview of the feature"
                        className="block max-h-60 max-w-full rounded border object-contain"
                    />
                    <LemonButton
                        icon={<IconTrash />}
                        size="small"
                        type="secondary"
                        tooltip="Remove image"
                        className="absolute top-2 right-2"
                        onClick={() => onChange?.('')}
                        data-attr="early-access-feature-image-remove"
                    />
                </div>
            ) : null}
            <div className="flex flex-wrap items-center gap-2">
                <LemonFileInput
                    accept="image/*"
                    multiple={false}
                    onChange={setFilesToUpload}
                    loading={uploading}
                    value={filesToUpload}
                    showUploadedFiles={false}
                    callToAction={
                        <LemonButton
                            type="secondary"
                            icon={<IconUpload />}
                            loading={uploading}
                            data-attr="early-access-feature-image-upload"
                        >
                            {value ? 'Replace image' : 'Upload image'}
                        </LemonButton>
                    }
                />
                <LemonInput
                    id={id}
                    className="flex-1 min-w-60"
                    placeholder="Or paste an image URL"
                    value={value ?? ''}
                    onChange={(newValue) => onChange?.(newValue)}
                    autoComplete="off"
                    spellCheck={false}
                />
            </div>
        </div>
    )
}
