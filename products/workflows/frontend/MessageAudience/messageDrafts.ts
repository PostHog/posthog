import { NEW_TEMPLATE } from '../TemplateLibrary/constants'

export interface MessageDraft {
    subject: string
    paragraphs: string[]
    preheader?: string
}

export type MessageDraftContext =
    | { kind: 'issue_fixed' }
    | { kind: 'issue_hit' }
    | { kind: 'feature_available'; featureName: string; featureDescription?: string | null }
    | { kind: 'feature_enrolled'; featureName: string; featureDescription?: string | null }
    | { kind: 'survey_responded' }

export interface MessageDraftEmail {
    subject: string
    preheader: string
    html: string
    text: string
    design: Record<string, any>
}

// pinned: URL search param, entry points link to /broadcasts/new and /workflows/new with it
export const EMAIL_PREFILL_PARAM = 'email'

const MAX_NAME_LENGTH = 100
const MAX_DESCRIPTION_LENGTH = 1000
const MAX_SUBJECT_LENGTH = 300
const MAX_PARAGRAPHS = 10
const MAX_PARAGRAPH_LENGTH = 2000

const GREETING = 'Hi there,'

function clip(value: string, max: number): string {
    const trimmed = value.trim()
    return trimmed.length > max ? `${trimmed.slice(0, max - 1).trimEnd()}…` : trimmed
}

export function draftMessage(context: MessageDraftContext): MessageDraft {
    switch (context.kind) {
        case 'issue_fixed':
            return {
                subject: 'We fixed an issue you ran into',
                paragraphs: [
                    GREETING,
                    'You recently ran into an error while using our product. We found the cause and fixed it.',
                    'Sorry for the trouble, and thanks for your patience.',
                ],
            }
        case 'issue_hit':
            return {
                subject: 'Sorry about the error you ran into',
                paragraphs: [
                    GREETING,
                    "It looks like you ran into an error while using our product. We know about it and we're working on a fix.",
                    'Sorry for the trouble.',
                ],
            }
        case 'feature_available': {
            const name = clip(context.featureName, MAX_NAME_LENGTH)
            return {
                subject: `${name} is now available`,
                paragraphs: [
                    GREETING,
                    `Thanks for signing up to try ${name} early. It's now available to you.`,
                    ...descriptionParagraph(context.featureDescription),
                    'Let us know what you think.',
                ],
            }
        }
        case 'feature_enrolled': {
            const name = clip(context.featureName, MAX_NAME_LENGTH)
            return {
                subject: `You have early access to ${name}`,
                paragraphs: [
                    GREETING,
                    `Thanks for joining the early access for ${name}. You can start using it now.`,
                    ...descriptionParagraph(context.featureDescription),
                    'Let us know what you think.',
                ],
            }
        }
        case 'survey_responded':
            return {
                subject: 'Thanks for your feedback',
                paragraphs: [
                    GREETING,
                    'Thanks for taking the time to answer our survey. Your answers help us decide what to work on next.',
                ],
            }
    }
}

function descriptionParagraph(description: string | null | undefined): string[] {
    const text = description ? clip(description, MAX_DESCRIPTION_LENGTH) : ''
    return text ? [text] : []
}

export function parseMessageDraftPrefill(raw: unknown): MessageDraft | null {
    let value = raw
    if (typeof raw === 'string') {
        try {
            value = JSON.parse(raw)
        } catch {
            return null
        }
    }
    if (!value || typeof value !== 'object' || Array.isArray(value)) {
        return null
    }
    const { subject, paragraphs } = value as Record<string, unknown>
    if (typeof subject !== 'string' || !subject.trim() || subject.length > MAX_SUBJECT_LENGTH) {
        return null
    }
    if (
        !Array.isArray(paragraphs) ||
        paragraphs.length === 0 ||
        paragraphs.length > MAX_PARAGRAPHS ||
        !paragraphs.every((paragraph) => typeof paragraph === 'string' && paragraph.length <= MAX_PARAGRAPH_LENGTH)
    ) {
        return null
    }
    return { subject: subject.trim(), paragraphs: paragraphs as string[] }
}

// Quotes stay as typed: the liquid renderer only decodes &lt;, &gt; and &amp; inside a tag,
// so an escaped quote would break a merge tag someone adds while editing the draft.
function escapeHtml(value: string): string {
    return value.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
}

function paragraphHtml(paragraph: string): string {
    return `<p style="line-height: 140%; margin: 0;">${escapeHtml(paragraph)}</p>`
}

/**
 * The draft as the email step stores it. Each paragraph is its own text block in the design, so
 * the visual editor opens with the draft in place and keeps the gap between paragraphs.
 */
export function messageDraftEmail(draft: MessageDraft): MessageDraftEmail {
    const body = draft.paragraphs
        .map(
            (paragraph) =>
                `<div style="padding: 10px; font-family: arial, helvetica, sans-serif; font-size: 14px; line-height: 140%; text-align: left;">${paragraphHtml(paragraph)}</div>`
        )
        .join('')
    return {
        subject: draft.subject,
        preheader: draft.preheader ?? '',
        html: `<!DOCTYPE html><html><head><meta http-equiv="Content-Type" content="text/html; charset=UTF-8" /><meta name="viewport" content="width=device-width, initial-scale=1.0" /></head><body style="margin: 0; padding: 0; background-color: #F7F8F9; color: #000000;"><table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="background-color: #F7F8F9;"><tr><td align="center"><table role="presentation" width="500" cellpadding="0" cellspacing="0" border="0" style="max-width: 500px; width: 100%;"><tr><td>${body}</td></tr></table></td></tr></table></body></html>`,
        text: draft.paragraphs.join('\n\n'),
        design: textBlocksDesign(draft.paragraphs),
    }
}

function textBlocksDesign(paragraphs: string[]): Record<string, any> {
    const design = JSON.parse(JSON.stringify(NEW_TEMPLATE.content.email.design))
    const column = design.body.rows[0].columns[0]
    const textBlock = column.contents.find((content: Record<string, any>) => content.type === 'text')
    column.contents = paragraphs.map((paragraph, index) => ({
        ...textBlock,
        id: `draft-text-${index + 1}`,
        values: {
            ...textBlock.values,
            text: paragraphHtml(paragraph),
            _meta: { htmlID: `u_content_text_${index + 1}`, htmlClassNames: 'u_content_text' },
        },
    }))
    design.counters = { u_row: 1, u_column: 1, u_content_text: paragraphs.length }
    return design
}
