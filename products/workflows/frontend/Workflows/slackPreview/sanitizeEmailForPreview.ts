// html-to-image copies the documents of nested frames and the current frame of a video into the capture.
// Both load on our own origin with the viewer's session, so an email that embeds one could publish the
// viewer's data to Slack.
const EMBEDDED_CONTENT_SELECTOR =
    'iframe, frame, frameset, object, embed, portal, video, audio, source, track, script, base, meta[http-equiv]'
const PREVIEW_CONTENT_SECURITY_POLICY =
    "frame-src 'none'; child-src 'none'; object-src 'none'; media-src 'none'; script-src 'none'; base-uri 'none'"

export function sanitizeEmailForPreview(html: string): Document {
    const emailDocument = new DOMParser().parseFromString(html, 'text/html')
    emailDocument.querySelectorAll(EMBEDDED_CONTENT_SELECTOR).forEach((element) => element.remove())
    const policy = emailDocument.createElement('meta')
    policy.setAttribute('http-equiv', 'Content-Security-Policy')
    policy.setAttribute('content', PREVIEW_CONTENT_SECURITY_POLICY)
    emailDocument.head.prepend(policy)
    return emailDocument
}
