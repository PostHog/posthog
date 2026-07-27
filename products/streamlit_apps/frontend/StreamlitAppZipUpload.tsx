import { LemonButton } from '@posthog/lemon-ui'

import { LemonFileInput } from 'lib/lemon-ui/LemonFileInput/LemonFileInput'

function humanFileSize(bytes: number): string {
    if (bytes < 1024) {
        return `${bytes} B`
    }
    if (bytes < 1024 * 1024) {
        return `${(bytes / 1024).toFixed(1)} KB`
    }
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

export function StreamlitAppZipUpload({
    file,
    onFileChange,
}: {
    file: File | null
    onFileChange: (file: File | null) => void
}): JSX.Element {
    if (!file) {
        return (
            <LemonFileInput
                accept=".zip"
                multiple={false}
                onChange={(files) => {
                    if (files.length > 0) {
                        onFileChange(files[0])
                    }
                }}
                showUploadedFiles={false}
                callToAction="Drag and drop your zip file here, or click to browse"
            />
        )
    }

    return (
        <div className="border rounded-lg p-4">
            <div className="flex items-center justify-between">
                <div>
                    <span className="font-medium">{file.name}</span>
                    <span className="text-muted ml-2">({humanFileSize(file.size)})</span>
                </div>
                <LemonButton size="small" type="secondary" onClick={() => onFileChange(null)}>
                    Remove
                </LemonButton>
            </div>
            <p className="text-xs text-muted mt-2 mb-0">
                Must contain app.py. Packages in requirements.txt will be validated on upload.
            </p>
        </div>
    )
}
