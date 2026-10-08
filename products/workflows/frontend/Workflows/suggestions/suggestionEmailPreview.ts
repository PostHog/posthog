// Inline styles and images that ship inside the email still render. Anything fetched from a server,
// such as a remote image or a tracking pixel, does not, so opening a suggestion contacts no host.
const BLOCK_REMOTE_RESOURCES =
    '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; img-src data:; style-src \'unsafe-inline\'">'

export function withRemoteResourcesBlocked(html: string): string {
    // A CSP meta tag only applies from the document head.
    const head = /<head\b[^>]*>/i.exec(html)
    if (head) {
        const end = head.index + head[0].length
        return html.slice(0, end) + BLOCK_REMOTE_RESOURCES + html.slice(end)
    }
    const root = /<html\b[^>]*>/i.exec(html)
    if (root) {
        const end = root.index + root[0].length
        return `${html.slice(0, end)}<head>${BLOCK_REMOTE_RESOURCES}</head>${html.slice(end)}`
    }
    const doctype = /^\s*<!doctype[^>]*>/i.exec(html)
    const end = doctype ? doctype[0].length : 0
    return html.slice(0, end) + BLOCK_REMOTE_RESOURCES + html.slice(end)
}
