import { useMemo, useState } from 'react'

import { LemonSegmentedButton } from '@posthog/lemon-ui'

import { withInertLinks } from 'scenes/hog-functions/email-templater/emailPreviewHtml'

const WIDTHS = { desktop: '100%', tablet: '600px', phone: '375px', small: '320px' }

export function EmailDocumentPreview({
    html,
    unsubscribeMissing,
}: {
    html: string
    unsubscribeMissing?: boolean
}): JSX.Element {
    const [width, setWidth] = useState<keyof typeof WIDTHS>('desktop')
    const srcDoc = useMemo(() => withInertLinks(html), [html])
    return (
        <div className="flex flex-col flex-1 min-h-0 gap-2 p-2 bg-surface-secondary">
            <div className="flex items-center gap-2 flex-wrap">
                <LemonSegmentedButton
                    size="xsmall"
                    value={width}
                    onChange={setWidth}
                    options={[
                        { value: 'desktop', label: 'Desktop', 'data-attr': 'email-editor-preview-desktop' },
                        { value: 'tablet', label: '600 px', 'data-attr': 'email-editor-preview-600' },
                        { value: 'phone', label: '375 px', 'data-attr': 'email-editor-preview-375' },
                        { value: 'small', label: '320 px', 'data-attr': 'email-editor-preview-320' },
                    ]}
                />
                <span className="text-xs text-secondary">
                    Variables show as written. Send a test email to see them filled in.
                </span>
                {unsubscribeMissing ? (
                    <span className="text-xs text-warning-dark">
                        This email has no unsubscribe link. Marketing emails need one.
                    </span>
                ) : null}
            </div>
            {html ? (
                <div className="flex-1 min-h-80 flex justify-center overflow-auto">
                    <iframe
                        title="Email preview"
                        sandbox=""
                        srcDoc={srcDoc}
                        className="h-full border bg-white"
                        style={{ width: WIDTHS[width], minHeight: 320 }}
                        data-attr="email-editor-preview-frame"
                    />
                </div>
            ) : (
                <p className="text-secondary m-0 p-8 text-center">Nothing to preview yet. Add some content first.</p>
            )}
        </div>
    )
}
