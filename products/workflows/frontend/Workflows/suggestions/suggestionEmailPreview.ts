// The suggested HTML is model-written, and a sandbox stops scripts but not subresources. Blocked, the
// preview renders inline styles and images that ship inside the email and contacts no server at all.
const BLOCKED_POLICY =
    "default-src 'none'; style-src 'unsafe-inline'; img-src data:; font-src data:; form-action 'none'"
// Only after a person asks: images, stylesheets and fonts load, and nothing else does.
const REMOTE_POLICY =
    "default-src 'none'; style-src 'unsafe-inline' https:; img-src data: https:; font-src data: https:; form-action 'none'"

function doctypeOf(doc: Document): string {
    const { doctype } = doc
    if (!doctype) {
        return ''
    }
    const publicId = doctype.publicId ? ` PUBLIC "${doctype.publicId}"` : ''
    const systemId = doctype.systemId ? `${doctype.publicId ? '' : ' SYSTEM'} "${doctype.systemId}"` : ''
    return `<!DOCTYPE ${doctype.name}${publicId}${systemId}>`
}

/**
 * Builds the document the comparison renders. The email is parsed by the same parser the frame uses, so
 * the policy lands in the real head however the email's own markup is written, rather than wherever a
 * pattern match in the untrusted text points. Parsing fetches nothing.
 */
export function emailPreviewDocument(html: string, { loadRemote }: { loadRemote: boolean }): string {
    const doc = new DOMParser().parseFromString(html, 'text/html')
    // A refresh navigates the frame itself, which no policy directive stops, and a base can repoint links.
    doc.querySelectorAll('meta[http-equiv], base').forEach((element) => element.remove())

    const policy = doc.createElement('meta')
    policy.httpEquiv = 'Content-Security-Policy'
    policy.content = loadRemote ? REMOTE_POLICY : BLOCKED_POLICY
    const referrer = doc.createElement('meta')
    referrer.name = 'referrer'
    referrer.content = 'no-referrer'
    doc.head.prepend(policy, referrer)

    // The email's own doctype decides its rendering mode, so the preview keeps it.
    return doctypeOf(doc) + doc.documentElement.outerHTML
}
