import { LemonBanner, LemonLabel, Spinner } from '@posthog/lemon-ui'

import { withInertLinks } from 'scenes/hog-functions/email-templater/emailPreviewHtml'

export function MessageTemplateTestPreview({
    email,
    loading,
}: {
    email: { subject: string; html: string; text: string; error?: string }
    loading: boolean
}): JSX.Element {
    if (loading) {
        return <Spinner />
    }
    if (email.error) {
        return <LemonBanner type="info">{email.error}</LemonBanner>
    }
    return (
        <div className="flex flex-col gap-2 ph-no-capture">
            <LemonLabel>Preview</LemonLabel>
            <div className="font-semibold break-words">{email.subject}</div>
            {email.html ? (
                <iframe
                    srcDoc={withInertLinks(email.html)}
                    sandbox=""
                    title="Test email preview"
                    className="w-full h-64 border rounded"
                />
            ) : (
                <pre className="whitespace-pre-wrap break-words font-sans">{email.text}</pre>
            )}
        </div>
    )
}
