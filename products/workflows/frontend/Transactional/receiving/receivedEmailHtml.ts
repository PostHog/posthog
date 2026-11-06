/** Wraps a stranger's HTML for a sandboxed iframe. Blocks remote content unless the reader asks, because a remote image tells its sender who opened the email and from where. */
export function buildReceivedEmailDocument(
    html: string,
    { allowRemoteImages }: { allowRemoteImages: boolean }
): string {
    const imageSources = allowRemoteImages ? 'data: https:' : 'data:'
    const policy = `default-src 'none'; img-src ${imageSources}; style-src 'unsafe-inline'; font-src data:; media-src 'none'`
    return `<!doctype html><html><head><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="${policy}"><base target="_blank"></head><body>${html}</body></html>`
}

/** True when the HTML loads an image from the internet, so the "Load remote images" button has something to do. */
export function hasRemoteImages(html: string): boolean {
    return /<img\b[^>]*\bsrc\s*=\s*["']?\s*(https?:)?\/\//i.test(html) || /url\(\s*["']?\s*(https?:)?\/\//i.test(html)
}
