import { messagingTemplatesList } from 'products/messaging/frontend/generated/api'
import { hogFlowsList } from 'products/workflows/frontend/generated/api'

import type { MessageDraftEmail } from './messageDrafts'

export type EmailBrandSource = 'template' | 'last_sent'

/** An email someone already designed, whose layout, colors, images and footer a new draft can borrow. */
export interface EmailBrand {
    source: EmailBrandSource
    html: string
    design: Record<string, any>
}

type DesignContent = Record<string, any>

// The template's own words. The draft replaces them, and everything else in the design stays.
const WORDING_TYPES = new Set(['text', 'heading', 'button'])
const SENT_BROADCASTS_TO_CHECK = 5
// The brand only decorates the draft, so a slow lookup must not hold up the draft itself.
const BRAND_TIMEOUT_MS = 5000

function plainText(html: string): string {
    return html
        .replace(/<[^>]*>/g, '')
        .replace(/&[a-z#0-9]+;/gi, ' ')
        .trim()
}

function holdsUnsubscribe(content: DesignContent): boolean {
    return JSON.stringify(content.values ?? {}).includes('unsubscribe_url')
}

function visibleEverywhere(content: DesignContent): boolean {
    return !content.values?.hideDesktop && !content.values?.hideMobile
}

/** The inbox preview text belongs to the template's own campaign, so the draft must not inherit it. */
function clearPreheader(doc: Document, design: Record<string, any>): void {
    const preheader = String(design.body?.values?.preheaderText ?? '').trim()
    if (!preheader) {
        return
    }
    design.body.values.preheaderText = ''
    for (const element of Array.from(doc.body.querySelectorAll('div, span'))) {
        const hidden = /display\s*:\s*none/i.test(element.getAttribute('style') ?? '')
        if (hidden && element.textContent?.trim() === preheader) {
            element.remove()
        }
    }
}

function designContents(design: Record<string, any>): DesignContent[][] | null {
    const rows = design?.body?.rows
    if (!Array.isArray(rows)) {
        return null
    }
    const columns: DesignContent[][] = []
    for (const row of rows) {
        if (!Array.isArray(row?.columns)) {
            return null
        }
        for (const column of row.columns) {
            if (!Array.isArray(column?.contents)) {
                return null
            }
            columns.push(column.contents)
        }
    }
    return columns
}

/**
 * The rendered block for each design block, column by column. Only HTML exported by the visual editor has this
 * shape, so anything else returns null and the draft keeps its plain layout.
 */
function renderedBlocks(doc: Document, columns: DesignContent[][]): Element[][] | null {
    const renderedColumns = Array.from(doc.querySelectorAll('.u-col'))
    if (renderedColumns.length !== columns.length) {
        return null
    }
    const blocks = renderedColumns.map((column) => Array.from(column.querySelectorAll(':scope > div > div > table')))
    return blocks.every((rendered, index) => rendered.length === columns[index].length) ? blocks : null
}

/**
 * The draft inside the brand's design: the brand keeps its layout, colors, images, dividers, social links and
 * unsubscribe block, its longest text block becomes the draft's paragraphs, and its other text is dropped.
 * Returns null when the brand can't be read, so the caller keeps the unbranded draft.
 */
export function applyEmailBrand(
    email: { design?: Record<string, any> | null },
    brand: EmailBrand
): Pick<MessageDraftEmail, 'html' | 'design'> | null {
    const draftColumns = email.design ? designContents(email.design) : null
    const draftParagraphs = (draftColumns ?? []).flat().filter((content) => content.type === 'text')
    if (draftParagraphs.length === 0 || typeof DOMParser === 'undefined') {
        return null
    }
    const design = JSON.parse(JSON.stringify(brand.design))
    const columns = designContents(design)
    if (!columns) {
        return null
    }
    const doc = new DOMParser().parseFromString(brand.html, 'text/html')
    const rendered = renderedBlocks(doc, columns)
    if (!rendered) {
        return null
    }

    let body: { column: number; index: number; length: number } | null = null
    columns.forEach((contents, column) =>
        contents.forEach((content, index) => {
            const candidate = content.type === 'text' && !holdsUnsubscribe(content) && visibleEverywhere(content)
            const length = candidate ? plainText(String(content.values?.text ?? '')).length : -1
            if (length >= 0 && (!body || length > body.length)) {
                body = { column, index, length }
            }
        })
    )
    if (!body) {
        return null
    }
    const { column: bodyColumn, index: bodyIndex } = body as { column: number; index: number }
    const bodyContent = columns[bodyColumn][bodyIndex]
    const bodyRendered = rendered[bodyColumn][bodyIndex]
    const bodyCell = bodyRendered.querySelector('td')
    const bodyWrapper = bodyCell?.firstElementChild
    if (!bodyCell || !bodyWrapper) {
        return null
    }

    const paragraphs = draftParagraphs.map((paragraph, index) => ({
        design: {
            ...bodyContent,
            id: `brand-draft-text-${index + 1}`,
            values: {
                ...bodyContent.values,
                text: paragraph.values?.text ?? '',
                _meta: { htmlID: `u_content_text_draft_${index + 1}`, htmlClassNames: 'u_content_text' },
            },
        },
        html: String(paragraph.values?.text ?? ''),
    }))

    columns.forEach((contents, column) => {
        for (let index = contents.length - 1; index >= 0; index--) {
            const isBody = column === bodyColumn && index === bodyIndex
            if (isBody) {
                for (const paragraph of paragraphs) {
                    const block = bodyRendered.cloneNode(true) as Element
                    const wrapper = block.querySelector('td')?.firstElementChild
                    if (wrapper) {
                        wrapper.innerHTML = paragraph.html
                    }
                    bodyRendered.parentNode?.insertBefore(block, bodyRendered)
                }
                bodyRendered.remove()
                contents.splice(index, 1, ...paragraphs.map((paragraph) => paragraph.design))
            } else if (WORDING_TYPES.has(contents[index].type) && !holdsUnsubscribe(contents[index])) {
                rendered[column][index].remove()
                contents.splice(index, 1)
            }
        }
    })
    design.counters = { ...design.counters, u_content_text: (design.counters?.u_content_text ?? 0) + paragraphs.length }
    clearPreheader(doc, design)

    return { html: `<!DOCTYPE html>${doc.documentElement.outerHTML}`, design }
}

function emailContent(value: unknown, templating: unknown): { html: string; design: Record<string, any> } | null {
    const email = value as { html?: unknown; design?: unknown } | null | undefined
    // Drafts render with Liquid, so a design written for Hog would keep its expressions as literal text.
    if (templating === 'hog') {
        return null
    }
    return email && typeof email.html === 'string' && email.design && typeof email.design === 'object'
        ? { html: email.html, design: email.design as Record<string, any> }
        : null
}

/**
 * The brand a new draft borrows: the newest saved email template, or when there is none, the email of the
 * broadcast sent most recently. Null when neither has a design the draft can go into.
 */
export async function loadEmailBrand(
    projectId: string,
    probe: { design?: Record<string, any> | null }
): Promise<EmailBrand | null> {
    try {
        return await Promise.race([
            findEmailBrand(projectId, probe),
            new Promise<null>((resolve) => setTimeout(() => resolve(null), BRAND_TIMEOUT_MS)),
        ])
    } catch {
        // The brand is a nicety. A draft without it is still complete, so a failed lookup stays quiet.
        return null
    }
}

async function findEmailBrand(
    projectId: string,
    probe: { design?: Record<string, any> | null }
): Promise<EmailBrand | null> {
    const templates = await messagingTemplatesList(projectId, { limit: 1 })
    const templateEmail = templates.results[0]?.content?.email
    const template = emailContent(templateEmail, (templateEmail as { templating?: unknown } | undefined)?.templating)
    if (template) {
        const brand: EmailBrand = { source: 'template', ...template }
        return applyEmailBrand(probe, brand) ? brand : null
    }
    const sent = await hogFlowsList(projectId, {
        origin_product: 'broadcasts',
        broadcast_status: 'sent',
        latest_send_first: true,
        limit: SENT_BROADCASTS_TO_CHECK,
    })
    for (const broadcast of sent.results ?? []) {
        const action = (broadcast.actions as Record<string, any>[] | undefined)?.find(
            (candidate) => candidate?.config?.template_id === 'template-email'
        )
        const content = emailContent(action?.config?.inputs?.email?.value, action?.config?.inputs?.email?.templating)
        if (content) {
            const brand: EmailBrand = { source: 'last_sent', ...content }
            if (applyEmailBrand(probe, brand)) {
                return brand
            }
        }
    }
    return null
}
