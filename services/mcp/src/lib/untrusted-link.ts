import { quoteUntrusted } from './quote-untrusted'

const TEMPLATE_TAG = /\{[{%]/

export function describeVariables(text: string): string {
    if (/^\s*\{\{(?:(?!\}\}).)*\}\}\s*$/s.test(text)) {
        return ' [a variable, filled when it is sent]'
    }
    return TEMPLATE_TAG.test(text) ? ' [has variables, filled when it is sent]' : ''
}

// A variable right after the host can extend it or turn it into a username, so the host counts only once it has ended.
export function describeLinkTarget(link: string): string {
    const firstTag = link.search(TEMPLATE_TAG)
    const fixed = firstTag === -1 ? link : link.slice(0, firstTag)
    if (firstTag !== -1 && !/^\s*[a-z][a-z0-9+.-]*:\/\/[^/?#\\]+[/?#\\]/i.test(fixed)) {
        return ' [where it leads is decided when it is sent]'
    }
    let url: URL
    try {
        url = new URL(fixed)
    } catch {
        return ' [not a full URL, the app decides what it means]'
    }
    if (!url.hostname) {
        return ` [no host, scheme ${quoteUntrusted(url.protocol.replace(/:$/, ''), 100)}]`
    }
    const notes = [`[host ${quoteUntrusted(url.hostname, Infinity)}]`]
    if (url.protocol !== 'https:' && url.protocol !== 'http:') {
        notes.push(`[scheme ${quoteUntrusted(url.protocol.replace(/:$/, ''), 100)}]`)
    }
    if (url.username || url.password) {
        notes.push('[the text before @ is a username, not the host]')
    }
    if (url.hostname.split('.').some((label) => label.startsWith('xn--'))) {
        notes.push('[international domain name, can look like another one]')
    }
    const written = /^[a-z][a-z0-9+.-]*:\/\/([^/?#]*)/i.exec(fixed)?.[1]
    const writtenHost = written?.slice(written.lastIndexOf('@') + 1).replace(/:\d*$/, '')
    if (writtenHost?.toLowerCase() !== url.hostname.toLowerCase()) {
        notes.push('[the host is written in another form, an app may read it differently]')
    }
    return ` ${notes.join(' ')}`
}
