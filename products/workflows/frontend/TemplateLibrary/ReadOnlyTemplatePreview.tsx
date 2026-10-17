import type { EmailTemplate } from 'scenes/hog-functions/email-templater/types'

import { EmailHtmlFrame } from './EmailHtmlFrame'

function PreviewField({ label, children }: { label: string; children: React.ReactNode }): JSX.Element {
    return (
        <div className="flex flex-col gap-1 min-w-0">
            <span className="text-xs font-semibold text-secondary">{label}</span>
            {children}
        </div>
    )
}

export function ReadOnlyTemplatePreview({ email }: { email: EmailTemplate }): JSX.Element {
    return (
        <div className="flex flex-col flex-1 gap-4 min-h-0" data-attr="message-template-read-only-preview">
            <div className="flex flex-col gap-3 rounded border bg-surface-primary p-3">
                <PreviewField label="Subject">
                    <span className="break-words">{email.subject}</span>
                </PreviewField>
                {email.preheader && (
                    <PreviewField label="Preheader">
                        <span className="break-words text-secondary">{email.preheader}</span>
                    </PreviewField>
                )}
            </div>
            <PreviewField label="HTML">
                <EmailHtmlFrame html={email.html} className="h-128 rounded border" />
            </PreviewField>
            <PreviewField label="Plain text">
                {email.text ? (
                    <pre className="m-0 rounded border bg-surface-primary p-3 text-sm whitespace-pre-wrap break-words">
                        {email.text}
                    </pre>
                ) : (
                    <span className="text-secondary">This template has no plain text version.</span>
                )}
            </PreviewField>
        </div>
    )
}
