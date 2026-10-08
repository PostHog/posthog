// A sandbox stops scripts but not subresources, so the policy keeps the page from fetching anything.
export const ARTIFACT_HTML_CSP =
    "default-src 'none'; style-src 'unsafe-inline'; img-src data:; font-src data:; form-action 'none'"

/**
 * Wraps untrusted HTML so the policy is the first thing the parser reads. The policy never goes inside the
 * untrusted text: a `<head>` in a comment, a title or a script would put it where the browser ignores it.
 * A second doctype, `html` or `head` later in the text is dropped by the parser, so the trusted head stays.
 */
export function withStrictCsp(html: string): string {
    return `<!doctype html><html><head><meta http-equiv="Content-Security-Policy" content="${ARTIFACT_HTML_CSP}"></head><body>${html}</body></html>`
}
