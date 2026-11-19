import { useContext } from 'react'

import { EmailPreviewThumbnail } from 'lib/components/EmailPreviewThumbnail/EmailPreviewThumbnail'
import {
    renderEmailPreviewMarked,
    renderEmailPreviewText,
    withUnresolvedChips,
} from 'scenes/hog-functions/email-templater/preview/emailPreview'

import { CanvasPreviewPersonContext } from '../CanvasPreviewPersonContext'
import { EmailContent, plainVariables } from '../stepValues'

export function EmailPreview({ email, title }: { email: EmailContent; title: string }): JSX.Element | null {
    const contextPerson = useContext(CanvasPreviewPersonContext)
    const person = email.liquid ? contextPerson : undefined
    if (email.html) {
        const html = person ? withUnresolvedChips(renderEmailPreviewMarked(email.html, person)) : email.html
        return (
            <div className="flex justify-center overflow-hidden rounded-md border bg-white">
                <EmailPreviewThumbnail html={html} title={title} size="card" />
            </div>
        )
    }
    return email.text ? (
        <div className="rounded-md border p-2.5 text-left text-[12.5px] leading-snug">
            <div className="line-clamp-6 whitespace-pre-line break-words">
                {person ? renderEmailPreviewText(email.text, person) : plainVariables(email.text)}
            </div>
        </div>
    ) : null
}
