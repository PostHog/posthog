const HTTPS_URL = /^https:\/\/[^\s/?#]+([/?#]\S*)?$/i

/** The URL when it is an absolute `https://` link, else undefined. Other schemes could open another app. */
export function safeHttpsUrl(url: string): string | undefined {
    const trimmed = url.trim()
    return HTTPS_URL.test(trimmed) ? trimmed : undefined
}
