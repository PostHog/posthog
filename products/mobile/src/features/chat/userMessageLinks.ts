interface UserMessageLink {
    offset: number
    label: string
    url: string
}

const WEB_LINK = /<(https?:\/\/[^\s<>"|\\]+)(?:\|([^<>\r\n]*))?>|\b(https?:\/\/[^\s<>"|\\`]+)/gi
const TRAILING_PUNCTUATION = /[.,!?;:'’”…]/

function decodeSlackEntities(text: string): string {
    // Decode ampersands last so a literal &amp;lt; becomes &lt; exactly once.
    return text.replaceAll('&lt;', '<').replaceAll('&gt;', '>').replaceAll('&amp;', '&')
}

function trimBareUrl(url: string): string {
    let parentheses = 0
    let brackets = 0
    for (const character of url) {
        if (character === '(') parentheses++
        if (character === ')') parentheses--
        if (character === '[') brackets++
        if (character === ']') brackets--
    }

    let end = url.length
    while (end > 0) {
        const last = url.charAt(end - 1)
        if (last === ')' && parentheses < 0) parentheses++
        else if (last === ']' && brackets < 0) brackets++
        else if (!TRAILING_PUNCTUATION.test(last)) break
        end--
    }
    return url.slice(0, end)
}

export function splitUserMessageLinks(text: string): (string | UserMessageLink)[] {
    const parts: (string | UserMessageLink)[] = []
    let end = 0
    for (const match of text.matchAll(WEB_LINK)) {
        const [matched, wrappedUrl, label, bareUrl = ''] = match
        const url = wrappedUrl ? decodeSlackEntities(wrappedUrl) : trimBareUrl(bareUrl)
        let destination: URL
        try {
            destination = new URL(url)
        } catch {
            continue
        }

        if (!destination.hostname || destination.username || destination.password) continue

        const caption = decodeSlackEntities(label ?? '').trim()
        const offset = match.index
        if (offset > end) parts.push(text.slice(end, offset))
        parts.push({ offset, label: caption && caption !== url ? `${caption} (${destination.host})` : url, url })
        end = offset + (wrappedUrl ? matched.length : url.length)
    }
    if (end < text.length) parts.push(text.slice(end))
    return parts
}
