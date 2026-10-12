import { BLANK_IMAGE, captureElementImage } from 'lib/utils/captureElementImage'

import { sanitizeEmailForPreview } from './sanitizeEmailForPreview'
import type { EmailStep } from './workflowPreviewOutline'

const PREVIEW_WIDTH_PX = 640
const MAX_PREVIEW_HEIGHT_PX = 6000
const FRAME_LOAD_TIMEOUT_MS = 10000
const MEASURING_HEIGHT_PX = 1
const IMAGE_LOAD_TIMEOUT_MS = 5000
const CAPTURE_FETCH_TIMEOUT_MS = 15000

export async function renderEmailPreviewPngBase64(step: EmailStep): Promise<string> {
    const emailDocument = sanitizeEmailForPreview(step.html)
    await inlineImages(emailDocument)
    emailDocument.body.prepend(buildInboxHeader(emailDocument, step))

    const frame = await mountOffscreenFrame(`<!doctype html>${emailDocument.documentElement.outerHTML}`)
    try {
        const root = frame.contentDocument?.documentElement
        if (!root) {
            throw new Error('The email preview frame has no document')
        }
        const height = Math.min(root.scrollHeight, MAX_PREVIEW_HEIGHT_PX)
        frame.style.height = `${height}px`
        const blob = await captureElementImage(root, {
            width: PREVIEW_WIDTH_PX,
            height,
            pixelRatio: 1,
            backgroundColor: '#ffffff',
            skipFonts: true,
            fetchRequestInit: { credentials: 'omit', signal: AbortSignal.timeout(CAPTURE_FETCH_TIMEOUT_MS) },
        })
        return await blobToBase64(blob)
    } finally {
        frame.remove()
    }
}

// The frame never gets allow-scripts, so neither script tags nor inline handlers in the email run.
// allow-same-origin only lets this code read the frame's document to capture it.
function mountOffscreenFrame(srcdoc: string): Promise<HTMLIFrameElement> {
    const frame = document.createElement('iframe')
    frame.setAttribute('sandbox', 'allow-same-origin')
    frame.setAttribute('aria-hidden', 'true')
    Object.assign(frame.style, {
        position: 'fixed',
        left: '-10000px',
        top: '0',
        width: `${PREVIEW_WIDTH_PX}px`,
        height: `${MEASURING_HEIGHT_PX}px`,
        border: '0',
    })
    return new Promise((resolve, reject) => {
        const timeout = setTimeout(() => {
            frame.remove()
            reject(new Error('The email preview took too long to load'))
        }, FRAME_LOAD_TIMEOUT_MS)
        frame.onload = () => {
            clearTimeout(timeout)
            resolve(frame)
        }
        frame.srcdoc = srcdoc
        document.body.appendChild(frame)
    })
}

// The app's connect-src blocks fetching most image hosts, which html-to-image relies on. An <img> may
// load from any https origin, so images whose host allows CORS are drawn to a canvas and inlined instead.
// Images on our own origin are fetched without cookies, so an email cannot pull the sharer's private data.
async function inlineImages(emailDocument: Document): Promise<void> {
    await Promise.all(
        Array.from(emailDocument.images).map(async (image) => {
            const source = image.getAttribute('src')
            if (!source || source.startsWith('data:')) {
                return
            }
            image.setAttribute('src', (await loadAsDataUrl(source)) ?? BLANK_IMAGE)
            image.removeAttribute('srcset')
        })
    )
}

async function loadAsDataUrl(source: string): Promise<string | null> {
    if (isOnAppOrigin(source)) {
        return await fetchWithoutSession(source)
    }
    return (await drawToDataUrl(source)) ?? (await drawToDataUrl(bypassingNonCorsCache(source)))
}

function isOnAppOrigin(source: string): boolean {
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
            signal: AbortSignal.timeout(IMAGE_LOAD_TIMEOUT_MS),
        })
        const blob = await response.blob()
        return response.ok && blob.type.startsWith('image/')
            ? `data:${blob.type};base64,${await blobToBase64(blob)}`
            : null
    } catch {
        return null
    }
}

function drawToDataUrl(source: string): Promise<string | null> {
    return new Promise((resolve) => {
        const image = new Image()
        const giveUp = setTimeout(() => {
            image.onload = image.onerror = null
            resolve(null)
        }, IMAGE_LOAD_TIMEOUT_MS)
        image.crossOrigin = 'anonymous'
        image.onload = () => {
            clearTimeout(giveUp)
            const canvas = document.createElement('canvas')
            canvas.width = image.naturalWidth
            canvas.height = image.naturalHeight
            try {
                canvas.getContext('2d')?.drawImage(image, 0, 0)
                resolve(canvas.toDataURL('image/png'))
            } catch {
                resolve(null)
            }
        }
        image.onerror = () => {
            clearTimeout(giveUp)
            resolve(null)
        }
        image.src = source
    })
}

function bypassingNonCorsCache(source: string): string {
    try {
        const url = new URL(source, window.location.href)
        url.searchParams.set('posthog_preview', String(Date.now()))
        return url.toString()
    } catch {
        return source
    }
}

function buildInboxHeader(emailDocument: Document, step: EmailStep): HTMLElement {
    const header = emailDocument.createElement('div')
    header.setAttribute(
        'style',
        'font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; text-align: left;' +
            'background: #f3f4f6; color: #111827; padding: 12px 16px; border-bottom: 1px solid #d1d5db; line-height: 1.4;'
    )
    const rows: [string, string][] = [
        ['From', step.from],
        ['Subject', step.subject],
        ['Preview text', step.preheader],
    ]
    for (const [label, value] of rows.filter(([, value]) => value)) {
        const row = emailDocument.createElement('div')
        row.setAttribute('style', 'font-size: 13px; margin: 2px 0;')
        const name = emailDocument.createElement('strong')
        name.textContent = `${label}: `
        row.append(name, emailDocument.createTextNode(value))
        header.append(row)
    }
    return header
}

function blobToBase64(blob: Blob): Promise<string> {
    return new Promise((resolve, reject) => {
        const reader = new FileReader()
        reader.onload = () => resolve(String(reader.result).split(',', 2)[1] ?? '')
        reader.onerror = () => reject(reader.error)
        reader.readAsDataURL(blob)
    })
}
