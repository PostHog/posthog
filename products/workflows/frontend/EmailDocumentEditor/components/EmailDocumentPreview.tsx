import { useMemo, useState } from 'react'

import { LemonSegmentedButton } from '@posthog/lemon-ui'

import { withInertLinks } from 'scenes/hog-functions/email-templater/emailPreviewHtml'
import { EmailPreviewPerson, renderEmailPreview } from 'scenes/hog-functions/email-templater/preview/emailPreview'
import { PreviewPerson } from 'scenes/hog-functions/email-templater/preview/emailPreviewPersonLogic'

import { withoutLiquidBetweenRows } from '../renderEmailHtml'
import { EmailPreviewPersonPicker } from './EmailPreviewPersonPicker'

const WIDTHS = { desktop: '100%', tablet: '600px', phone: '375px', small: '320px' }

// Until someone is picked, conditions and assignments run against a person with no properties, so the preview lays
// out like a sent email instead of showing the Liquid code. A plain variable with no value stays as written.
const PREVIEW_PERSON: EmailPreviewPerson = { id: 'preview', properties: {} }

function showsAnything(html: string): boolean {
    const doc = new DOMParser().parseFromString(html, 'text/html')
    // Hidden preview text isn't something the reader sees.
    doc.querySelectorAll('style, script, title, [style*="display:none"], [style*="display: none"]').forEach((element) =>
        element.remove()
    )
    return !!doc.body?.textContent?.trim() || !!doc.querySelector('img')
}

/** An email made only of variables or conditions renders blank for a person with no properties, so it shows as written. */
function previewHtml(
    html: string,
    liquid: boolean | undefined,
    person: EmailPreviewPerson
): { html: string; rendered: boolean } {
    if (!liquid) {
        return { html, rendered: false }
    }
    const rendered = renderEmailPreview(html, person)
    // An unchanged result means Liquid couldn't parse the email, so nothing ran.
    return rendered !== html && (showsAnything(rendered) || !showsAnything(html))
        ? { html: rendered, rendered: true }
        : { html, rendered: false }
}

export function EmailDocumentPreview({
    html,
    liquid,
    unsubscribeMissing,
    person: pickedPerson,
    onPersonChange,
}: {
    html: string
    liquid?: boolean
    unsubscribeMissing?: boolean
    person: PreviewPerson | null
    onPersonChange: (person: PreviewPerson | null) => void
}): JSX.Element {
    const [width, setWidth] = useState<keyof typeof WIDTHS>('desktop')
    const person = liquid ? pickedPerson : null
    const preview = useMemo(() => previewHtml(html, liquid, person ?? PREVIEW_PERSON), [html, liquid, person])
    const srcDoc = useMemo(() => withInertLinks(withoutLiquidBetweenRows(preview.html)), [preview.html])
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
                {liquid ? <EmailPreviewPersonPicker person={pickedPerson} onChange={onPersonChange} /> : null}
                <span className="text-xs text-secondary">
                    {!preview.rendered
                        ? 'Variables and conditions show as written. Send a test email to see them filled in.'
                        : person
                          ? "Filled in with this person's properties. Variables they have no value for show as written."
                          : 'Conditions run as if the person has no properties. Pick a person to see their data filled in.'}
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
                        // The recorder serializes `srcdoc`, and with a person picked it holds their values.
                        className="ph-no-capture h-full border bg-white"
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
