import { useState } from 'react'

import { LemonButton, LemonInput } from '@posthog/lemon-ui'

export function SourceFileForm({
    initialUrl,
    saving,
    onSave,
}: {
    initialUrl: string | null
    saving: boolean
    onSave: (sourceUrl: string) => void
}): JSX.Element {
    const [url, setUrl] = useState(initialUrl ?? '')
    const trimmed = url.trim()
    const disabledReason = !trimmed
        ? 'Paste a link to the file first'
        : !/^https?:\/\//i.test(trimmed)
          ? 'The link starts with https:// or http://'
          : trimmed === initialUrl
            ? 'This file is already linked'
            : undefined
    return (
        <form
            className="flex flex-col gap-2 p-2 w-100 max-w-full"
            onSubmit={(event) => {
                event.preventDefault()
                if (!disabledReason) {
                    onSave(trimmed)
                }
            }}
        >
            <div className="font-semibold">Link this email to the file that sends it</div>
            <p className="m-0 text-secondary">
                Paste the link to the file in your repository. The Code tag then opens it.
            </p>
            <LemonInput
                autoFocus
                placeholder="https://github.com/acme/web/blob/main/src/emails/receipt.tsx"
                value={url}
                onChange={setUrl}
                data-attr="code-email-source-file-input"
            />
            <div className="flex justify-end">
                <LemonButton
                    type="primary"
                    size="small"
                    htmlType="submit"
                    loading={saving}
                    disabledReason={disabledReason}
                    data-attr="code-email-source-file-save"
                >
                    Save
                </LemonButton>
            </div>
        </form>
    )
}
