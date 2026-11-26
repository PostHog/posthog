import type { PushTemplateApi } from 'products/messaging/frontend/generated/api.schemas'

// Any Liquid output `{{ … }}` or tag `{% … %}`, and a `variables.<name>` reference inside one.
const LIQUID_EXPRESSION = /\{\{[\s\S]*?\}\}|\{%[\s\S]*?%\}/g
const VARIABLE_REFERENCE = /\bvariables\.([A-Za-z_][A-Za-z0-9_]*)/g

export interface PushDraft {
    title: string
    body: string
    image: string
    link: string
    /** The custom data as the person typed it: a JSON object of string values. */
    data: string
    channels: number[]
}

export const EMPTY_PUSH_DRAFT: PushDraft = { title: '', body: '', image: '', link: '', data: '', channels: [] }

export function pushDraftFrom(push: PushTemplateApi | null | undefined): PushDraft {
    return {
        title: push?.title ?? '',
        body: push?.body ?? '',
        image: push?.image ?? '',
        link: push?.link ?? '',
        data: push?.data && Object.keys(push.data).length ? JSON.stringify(push.data, null, 2) : '',
        channels: push?.channels ?? [],
    }
}

/** Why the custom data can't be saved, or null. The data must be a JSON object whose values are strings. */
export function pushDataError(data: string): string | null {
    if (!data.trim()) {
        return null
    }
    let parsed: unknown
    try {
        parsed = JSON.parse(data)
    } catch {
        return 'Enter valid JSON, like {"order_id": "{{ variables.order_id }}"}.'
    }
    if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) {
        return 'Enter a JSON object of keys and values.'
    }
    if (Object.values(parsed).some((value) => typeof value !== 'string')) {
        return 'Each value must be a string, because Firebase only delivers string values.'
    }
    return null
}

/** Why the draft can't be published, or null. */
export function pushDraftError(draft: PushDraft): string | null {
    if (!draft.channels.length) {
        return 'Choose at least one app to send through'
    }
    if (!draft.title.trim()) {
        return 'Add a title'
    }
    if (!draft.body.trim()) {
        return 'Add a message'
    }
    return pushDataError(draft.data)
}

export function pushContentFrom(draft: PushDraft): PushTemplateApi {
    return {
        title: draft.title,
        body: draft.body,
        image: draft.image.trim(),
        link: draft.link.trim(),
        data: draft.data.trim() ? (JSON.parse(draft.data) as Record<string, string>) : {},
        channels: draft.channels,
    }
}

/** The `message_data` keys a push reads, in the order they first appear. */
export function variablesInPush(draft: PushDraft): string[] {
    const source = [draft.title, draft.body, draft.image, draft.link, draft.data].join('\n')
    const expressions = source.match(LIQUID_EXPRESSION) ?? []
    return [
        ...new Set(
            expressions.flatMap((expression) => [...expression.matchAll(VARIABLE_REFERENCE)].map((match) => match[1]))
        ),
    ]
}
