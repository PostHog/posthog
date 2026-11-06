/** Wraps a stranger's HTML for a sandboxed iframe. Blocks remote content unless the reader asks, because a remote image tells its sender who opened the email and from where. */
export function buildReceivedEmailDocument(
    html: string,
    { allowRemoteImages }: { allowRemoteImages: boolean }
): string {
    const imageSources = allowRemoteImages ? 'data: https:' : 'data:'
    const policy = `default-src 'none'; img-src ${imageSources}; style-src 'unsafe-inline'; font-src data:; media-src 'none'`
    return `<!doctype html><html><head><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="${policy}"><base target="_blank"></head><body>${html}</body></html>`
}

const REMOTE_URL_START = /^(?:https?:)?\/\//i
const LONGEST_URL_START = 'https://'.length
const WHITESPACE = /\s/

/** Whether a remote URL starts at `start`, after any whitespace and one quote. */
function remoteUrlStartsAt(html: string, start: number): boolean {
    let index = start
    const skipWhitespace = (): void => {
        while (index < html.length && WHITESPACE.test(html[index])) {
            index++
        }
    }
    skipWhitespace()
    if (html[index] === '"' || html[index] === "'") {
        index++
        skipWhitespace()
    }
    return REMOTE_URL_START.test(html.slice(index, index + LONGEST_URL_START))
}

/**
 * True when the HTML loads an image from the internet, so the "Load remote images" button has something to do.
 *
 * A stranger writes this HTML and it can be long, so this scans forward only, which keeps the time linear in its size.
 */
export function hasRemoteImages(html: string): boolean {
    for (const urlMatch of html.matchAll(/url\(/gi)) {
        if (remoteUrlStartsAt(html, urlMatch.index + urlMatch[0].length)) {
            return true
        }
    }
    const lowered = html.toLowerCase()
    let scannedTo = 0
    for (const tagMatch of lowered.matchAll(/<(?:img|source)\b/g)) {
        if (tagMatch.index < scannedTo) {
            continue
        }
        const closing = lowered.indexOf('>', tagMatch.index)
        scannedTo = closing === -1 ? lowered.length : closing
        for (const srcMatch of lowered.slice(tagMatch.index, scannedTo).matchAll(/\bsrc(?:set)?\s*=/g)) {
            if (remoteUrlStartsAt(html, tagMatch.index + srcMatch.index + srcMatch[0].length)) {
                return true
            }
        }
    }
    return false
}
