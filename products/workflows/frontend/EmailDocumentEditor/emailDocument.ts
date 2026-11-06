import type { JSONContent } from '@tiptap/core'

export const EMAIL_DOCUMENT_VERSION = 1

/** pinned: stored in saved designs, renaming orphans every document saved under the old key */
export const EMAIL_DOCUMENT_DESIGN_KEY = 'emailDocument'

export interface EmailSides {
    top: number
    right: number
    bottom: number
    left: number
}

export type EmailTextAlign = 'left' | 'center' | 'right'

/** The per-block overrides. Anything left out falls back to the page style. */
export interface EmailBlockStyle {
    color?: string
    backgroundColor?: string
    fontSize?: number
    lineHeight?: number
    letterSpacing?: number
    uppercase?: boolean
    fontWeight?: number
    textAlign?: EmailTextAlign
    padding?: EmailSides
    borderRadius?: number
    borderWidth?: number
    borderColor?: string
    width?: number
    /** Divider only: its thickness and length are styled separately from the block box. */
    lineWidth?: number
    /** Button only: the padding inside the button. */
    innerPaddingX?: number
    innerPaddingY?: number
}

export interface EmailPageStyle {
    backgroundColor: string
    padding: number
    align: EmailTextAlign
    bodyBackgroundColor: string
    bodyWidth: number
    bodyPadding: EmailSides
    bodyBorderRadius: number
    bodyBorderWidth: number
    bodyBorderColor: string
    fontFamily: string
    textColor: string
    fontSize: number
    lineHeight: number
    linkColor: string
    h1Size: number
    h2Size: number
    h3Size: number
    buttonBackgroundColor: string
    buttonTextColor: string
    buttonBorderRadius: number
    globalCss: string
}

export const EMAIL_SAFE_FONTS: { label: string; value: string }[] = [
    { label: 'System', value: "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif" },
    { label: 'Arial', value: 'Arial, Helvetica, sans-serif' },
    { label: 'Georgia', value: "Georgia, 'Times New Roman', serif" },
    { label: 'Tahoma', value: 'Tahoma, Verdana, Segoe, sans-serif' },
    { label: 'Trebuchet MS', value: "'Trebuchet MS', Helvetica, sans-serif" },
    { label: 'Courier New', value: "'Courier New', Courier, monospace" },
]

export const DEFAULT_EMAIL_PAGE_STYLE: EmailPageStyle = {
    backgroundColor: '#ffffff',
    padding: 0,
    align: 'center',
    bodyBackgroundColor: '#ffffff',
    bodyWidth: 600,
    bodyPadding: { top: 24, right: 24, bottom: 24, left: 24 },
    bodyBorderRadius: 0,
    bodyBorderWidth: 0,
    bodyBorderColor: '#e5e5e5',
    fontFamily: EMAIL_SAFE_FONTS[0].value,
    textColor: '#111111',
    fontSize: 16,
    lineHeight: 150,
    linkColor: '#1d4aff',
    h1Size: 32,
    h2Size: 24,
    h3Size: 20,
    buttonBackgroundColor: '#111111',
    buttonTextColor: '#ffffff',
    buttonBorderRadius: 6,
    globalCss: '',
}

export interface EmailDocument {
    version: number
    /** A TipTap document whose `attrs.page` holds the partial page style, so a page change is undoable like any edit. */
    doc: JSONContent
}

export function resolvePageStyle(page: Partial<EmailPageStyle> | null | undefined): EmailPageStyle {
    return { ...DEFAULT_EMAIL_PAGE_STYLE, ...page }
}

export function emptyEmailDoc(): JSONContent {
    return { type: 'doc', attrs: { page: {} }, content: [{ type: 'paragraph' }] }
}

/** What a new template starts with, so people see a filled-in example like the old editor's. */
export function starterEmailDoc(): JSONContent {
    return {
        type: 'doc',
        attrs: { page: {} },
        content: [
            { type: 'paragraph', content: [{ type: 'text', text: 'Hello from PostHog!' }] },
            {
                type: 'emailButton',
                attrs: { href: 'https://posthog.com/' },
                content: [{ type: 'text', text: 'Learn more' }],
            },
        ],
    }
}

function isEmptyParagraph(node: JSONContent): boolean {
    return node.type === 'paragraph' && !node.content?.length
}

/** True when there is nothing to send: a page style on its own is not content. */
export function isEmailDocEmpty(doc: JSONContent): boolean {
    return (doc.content ?? []).every(isEmptyParagraph)
}

type DesignLike = Record<string, any> | null | undefined

export function withoutEmailDocument<T extends DesignLike>(design: T): T {
    if (!design || !(EMAIL_DOCUMENT_DESIGN_KEY in design)) {
        return design
    }
    const { [EMAIL_DOCUMENT_DESIGN_KEY]: _document, ...rest } = design
    return rest as T
}

function wrappedHtmlOf(design: DesignLike): string | undefined {
    const html = design?.body?.rows?.[0]?.columns?.[0]?.contents?.[0]?.values?.html
    return typeof html === 'string' ? html : undefined
}

/**
 * The document a saved email can open with, or null when it has to stay on the old editor. The design also
 * carries the html the document rendered when it was saved, so anything that changed the email since then (the
 * old editor, the API, an agent) shows as a mismatch, and a stale document is never allowed to overwrite it.
 */
export function emailDocumentFromValue(value: { html?: string | null; design?: DesignLike } | null | undefined): {
    document: EmailDocument | null
    stale: boolean
} {
    const candidate = value?.design?.[EMAIL_DOCUMENT_DESIGN_KEY]
    if (!candidate || typeof candidate !== 'object' || candidate.version !== EMAIL_DOCUMENT_VERSION || !candidate.doc) {
        return { document: null, stale: false }
    }
    if (wrappedHtmlOf(value?.design) !== (value?.html ?? '')) {
        return { document: null, stale: true }
    }
    return { document: candidate as EmailDocument, stale: false }
}

/** A brand new email has nothing the new editor could lose. */
export function isBlankEmail(value: { html?: string | null; design?: DesignLike } | null | undefined): boolean {
    return !value?.html && !value?.design
}
