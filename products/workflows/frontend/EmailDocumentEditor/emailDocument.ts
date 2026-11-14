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
    fontFamily?: string
    /** The stylesheet a web font loads from. */
    fontUrl?: string
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
    columnGap?: number
    linkColor?: string
    linkUnderline?: boolean
    listIndent?: number
    listItemGap?: number
    /** HTML blocks only: leave the text settings to the block's own markup. */
    inheritText?: boolean
    /** Divider only: its thickness and length are styled separately from the block box. */
    lineWidth?: number
    /** Button only: a percentage of the space it sits in. Left out, it fits its label. */
    buttonWidth?: number
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
    /** The stylesheet a web font loads from. */
    fontUrl: string
    /** The hidden line that inboxes show after the subject. */
    previewText: string
    /** A lone full HTML document normally goes out as written. This puts it in the email's body instead. */
    wrapFullHtml: boolean
    /** Set on converted emails: the old editor's page-wide styles, which custom HTML in the email may rely on. */
    oldEditorStyles: boolean
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

const GOOGLE_FONTS = 'https://fonts.googleapis.com/css2?display=swap&family='

/** Web fonts fall back to the listed sans-serif or serif in email apps that don't load them, such as Outlook and Gmail. */
export const EMAIL_FONTS: { label: string; value: string; url?: string }[] = [
    { label: 'System', value: "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif" },
    { label: 'Arial', value: 'Arial, Helvetica, sans-serif' },
    { label: 'Georgia', value: "Georgia, 'Times New Roman', serif" },
    { label: 'Tahoma', value: 'Tahoma, Verdana, Segoe, sans-serif' },
    { label: 'Trebuchet MS', value: "'Trebuchet MS', Helvetica, sans-serif" },
    { label: 'Courier New', value: "'Courier New', Courier, monospace" },
    { label: 'Inter', value: 'Inter, Helvetica, Arial, sans-serif', url: `${GOOGLE_FONTS}Inter:wght@400;600;700` },
    { label: 'Lato', value: 'Lato, Helvetica, Arial, sans-serif', url: `${GOOGLE_FONTS}Lato:wght@400;700` },
    {
        label: 'Montserrat',
        value: 'Montserrat, Helvetica, Arial, sans-serif',
        url: `${GOOGLE_FONTS}Montserrat:wght@400;600;700`,
    },
    {
        label: 'Open Sans',
        value: "'Open Sans', Helvetica, Arial, sans-serif",
        url: `${GOOGLE_FONTS}Open+Sans:wght@400;600;700`,
    },
    {
        label: 'Playfair Display',
        value: "'Playfair Display', Georgia, serif",
        url: `${GOOGLE_FONTS}Playfair+Display:wght@400;700`,
    },
    { label: 'Roboto', value: 'Roboto, Helvetica, Arial, sans-serif', url: `${GOOGLE_FONTS}Roboto:wght@400;500;700` },
]

/** The font list, plus the font this email already uses when it came from somewhere else. */
export function fontOptions(current: string | undefined): { label: string; value: string }[] {
    return !current || EMAIL_FONTS.some((font) => font.value === current)
        ? EMAIL_FONTS
        : [{ label: current.split(',')[0].replace(/['"]/g, ''), value: current }, ...EMAIL_FONTS]
}

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
    fontFamily: EMAIL_FONTS[0].value,
    fontUrl: '',
    previewText: '',
    wrapFullHtml: false,
    oldEditorStyles: false,
    textColor: '#111111',
    fontSize: 16,
    lineHeight: 150,
    linkColor: '#1d4aff',
    h1Size: 32,
    h2Size: 24,
    h3Size: 20,
    buttonBackgroundColor: '#3aaee0',
    buttonTextColor: '#ffffff',
    buttonBorderRadius: 4,
    globalCss: '',
}

export interface EmailDocument {
    version: number
    /** A TipTap document whose `attrs.page` holds the partial page style, so a page change is undoable like any edit. */
    doc: JSONContent
    /** The html it rendered when saved. Left out by documents saved before the design held the full old-editor email. */
    html?: string
}

const PAGE_COLOR = /^(#[0-9a-f]{3,8}|rgba?\([\d\s.,%]+\)|[a-z]+)$/i

function pageValue(key: keyof EmailPageStyle, value: unknown): unknown {
    const fallback = DEFAULT_EMAIL_PAGE_STYLE[key]
    if (typeof fallback === 'number') {
        const number = typeof value === 'string' && value.trim() !== '' ? Number(value) : value
        return typeof number === 'number' && Number.isFinite(number) ? number : fallback
    }
    if (typeof fallback === 'boolean') {
        return typeof value === 'boolean' ? value : fallback
    }
    if (key === 'bodyPadding') {
        const sides = (value ?? {}) as Record<string, unknown>
        const defaults = DEFAULT_EMAIL_PAGE_STYLE.bodyPadding
        const side = (name: keyof EmailSides): number =>
            typeof sides[name] === 'number' && Number.isFinite(sides[name]) ? (sides[name] as number) : defaults[name]
        return value && typeof value === 'object'
            ? { top: side('top'), right: side('right'), bottom: side('bottom'), left: side('left') }
            : fallback
    }
    if (typeof value !== 'string') {
        return fallback
    }
    if (key.endsWith('Color')) {
        return PAGE_COLOR.test(value.trim()) ? value.trim() : fallback
    }
    if (key === 'align') {
        return value === 'left' || value === 'center' || value === 'right' ? value : fallback
    }
    if (key === 'fontFamily') {
        return value.replace(/[;"<>{}()\\]/g, '')
    }
    if (key === 'fontUrl') {
        return /^https:\/\/[^\s"'()<>]+$/i.test(value) ? value : ''
    }
    return value
}

/** The page style with defaults filled in. A saved value can come from any writer, and the canvas puts it into the app page. */
export function resolvePageStyle(page: Partial<EmailPageStyle> | null | undefined): EmailPageStyle {
    const resolved = { ...DEFAULT_EMAIL_PAGE_STYLE } as Record<string, unknown>
    for (const key of Object.keys(DEFAULT_EMAIL_PAGE_STYLE) as (keyof EmailPageStyle)[]) {
        if (page && key in page) {
            resolved[key] = pageValue(key, page[key])
        }
    }
    return resolved as unknown as EmailPageStyle
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

/** Every web font stylesheet the email needs, on the page or on a block. */
export function emailFontUrls(doc: JSONContent): string[] {
    const urls = new Set<string>()
    const visit = (node: JSONContent): void => {
        const url = node.attrs?.emailStyle?.fontUrl
        if (url) {
            urls.add(url)
        }
        node.content?.forEach(visit)
    }
    const pageUrl = doc.attrs?.page?.fontUrl
    if (pageUrl) {
        urls.add(pageUrl)
    }
    visit(doc)
    return [...urls].filter((url) => /^https:\/\//i.test(url))
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
    const savedHtml = typeof candidate.html === 'string' ? candidate.html : wrappedHtmlOf(value?.design)
    // Writing in the plain text tab clears the html. The document stays, as the old editor's design does.
    if (value?.html && savedHtml !== value.html) {
        return { document: null, stale: true }
    }
    return { document: candidate as EmailDocument, stale: false }
}

/** A brand new email has nothing the new editor could lose. */
export function isBlankEmail(value: { html?: string | null; design?: DesignLike } | null | undefined): boolean {
    return !value?.html && !value?.design
}
