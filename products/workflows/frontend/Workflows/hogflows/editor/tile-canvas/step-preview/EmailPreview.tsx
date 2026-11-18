import { EmailPreviewThumbnail } from 'lib/components/EmailPreviewThumbnail/EmailPreviewThumbnail'

import { EmailContent, plainVariables } from '../stepValues'

export function EmailPreview({ email, title }: { email: EmailContent; title: string }): JSX.Element | null {
    if (email.html) {
        return (
            <div className="flex justify-center overflow-hidden rounded-md border bg-white">
                <EmailPreviewThumbnail html={email.html} title={title} size="card" />
            </div>
        )
    }
    return email.text ? (
        <div className="rounded-md border p-2.5 text-left text-[12.5px] leading-snug">
            <div className="line-clamp-6 whitespace-pre-line break-words">{plainVariables(email.text)}</div>
        </div>
    ) : null
}
