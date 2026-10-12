import { BLANK_IMAGE } from 'lib/utils/captureElementImage'

// Same-origin requests carry the sharer's session, and html-to-image reuses resources another capture
// fetched with it. Every same-origin resource is therefore inlined here, fetched without cookies, so the
// capture never requests one itself.
const RESOURCE_FETCH_TIMEOUT_MS = 5000
const BYTES_PER_CHUNK = 0x8000
const CSS_URL = /url\(\s*(['"]?)(.*?)\1\s*\)/g
const SVG_IMAGE_HREF_ATTRIBUTES = ['href', 'xlink:href']

export async function inlineSameOriginResources(emailDocument: Document): Promise<void> {
    await Promise.all([
        ...Array.from(emailDocument.images).map((image) => inlineAttribute(image, 'src', BLANK_IMAGE)),
        ...Array.from(emailDocument.querySelectorAll('image')).flatMap((image) =>
            SVG_IMAGE_HREF_ATTRIBUTES.map((attribute) => inlineAttribute(image, attribute, BLANK_IMAGE))
        ),
        ...Array.from(emailDocument.querySelectorAll<HTMLElement>('[style]')).map(async (element) =>
            element.setAttribute('style', await inlineCssUrls(element.getAttribute('style') ?? ''))
        ),
        ...Array.from(emailDocument.querySelectorAll('style')).map(async (style) => {
            style.textContent = await inlineCssUrls(style.textContent ?? '')
        }),
    ])
}

async function inlineAttribute(element: Element, attribute: string, fallback: string): Promise<void> {
    const source = element.getAttribute(attribute)
    if (source && isOnAppOrigin(source)) {
        element.setAttribute(attribute, (await fetchWithoutSession(source)) ?? fallback)
        element.removeAttribute('srcset')
    }
}

async function inlineCssUrls(css: string): Promise<string> {
    const replacements = await Promise.all(
        Array.from(css.matchAll(CSS_URL), async ([match, , source]) => {
            if (!isOnAppOrigin(source)) {
                return [match, match]
            }
            const dataUrl = await fetchWithoutSession(source)
            return [match, dataUrl ? `url("${dataUrl}")` : 'none']
        })
    )
    return replacements.reduce((result, [match, replacement]) => result.replace(match, replacement), css)
}

function isOnAppOrigin(source: string): boolean {
    if (source.startsWith('data:')) {
        return false
    }
    try {
        return new URL(source, window.location.href).origin === window.location.origin
    } catch {
        return true
    }
}

async function fetchWithoutSession(source: string): Promise<string | null> {
    try {
        const response = await fetch(source, {
            credentials: 'omit',
            signal: AbortSignal.timeout(RESOURCE_FETCH_TIMEOUT_MS),
        })
        const blob = await response.blob()
        return response.ok && blob.type.startsWith('image/') ? await blobToDataUrl(blob) : null
    } catch {
        return null
    }
}

async function blobToDataUrl(blob: Blob): Promise<string> {
    const bytes = new Uint8Array(await blob.arrayBuffer())
    let binary = ''
    for (let offset = 0; offset < bytes.length; offset += BYTES_PER_CHUNK) {
        binary += String.fromCharCode(...bytes.subarray(offset, offset + BYTES_PER_CHUNK))
    }
    return `data:${blob.type};base64,${btoa(binary)}`
}
