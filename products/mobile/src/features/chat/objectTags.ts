import type MarkdownIt from 'markdown-it'
import { OBJECT_KIND_ALIASES, OBJECT_KIND_DATA, type ObjectKindData } from './objectKinds.generated'

export interface ObjectRef {
    kind: string
    id: string
    label: string
}
export type ObjectCardSpec =
    | { mode: 'insight'; shortId: string; title?: string }
    | { mode: 'hogql'; query: string; title?: string }
const kinds: Record<string, ObjectKindData> = OBJECT_KIND_DATA
const aliases: Record<string, string> = OBJECT_KIND_ALIASES
const TAG = /^<([a-z][\w-]*)((?:\s+[a-z][\w-]*\s*=\s*"[^"]*")*)\s*(?:\/>|>([\s\S]*?)<\/\1\s*>)/
const PART = /\s+|[a-z][\w-]*|=|"[^"]*"|"[^"]*$|\/$/y
export function objectKind(name: string): string | undefined {
    return kinds[name] ? name : aliases[name]
}
function decode(value: string): string {
    return value.replace(
        /&(amp|lt|gt|quot|apos);/g,
        (_, key: string) => ({ amp: '&', lt: '<', gt: '>', quot: '"', apos: "'" })[key] ?? ''
    )
}
function matchTag(
    src: string
): { raw: string; kind?: string; attrs: Record<string, string>; body?: string } | undefined {
    const match = TAG.exec(src)
    if (!match) return undefined
    const attrs: Record<string, string> = {}
    for (const attr of (match[2] ?? '').matchAll(/([a-z][\w-]*)\s*=\s*"([^"]*)"/g))
        attrs[attr[1] ?? ''] = decode(attr[2] ?? '')
    const kind = objectKind(match[1] ?? '')
    return kind || 'id' in attrs ? { raw: match[0], kind, attrs, body: match[3] } : undefined
}
export function objectRef(tag: NonNullable<ReturnType<typeof matchTag>>): ObjectRef | undefined {
    const { kind, attrs, body } = tag
    if (!kind) return undefined
    const id = (kind === 'hogql' ? body : attrs.id)?.trim()
    if (!id) return undefined
    return {
        kind,
        id,
        label: attrs.title?.trim() || (kind === 'hogql' ? attrs.label?.trim() || 'SQL query' : body?.trim() || id),
    }
}
function unfinished(src: string): boolean {
    const head = /^<([a-z][\w-]*)/.exec(src)
    if (!head || !objectKind(head[1] ?? '')) return false
    const open = /^<[a-z][\w-]*(?:\s+[a-z][\w-]*\s*=\s*"[^"]*")*\s*>/.exec(src)
    if (open) return !new RegExp(`</${head[1]}\\s*>`).test(src)
    PART.lastIndex = head[0].length
    while (PART.lastIndex < src.length) if (!PART.exec(src)) return false
    return true
}
export function objectWebUrl(host: string, projectId: number, kind: string, id: string): string | undefined {
    const meta = kinds[objectKind(kind) ?? kind]
    if (!/^https?:\/\//i.test(host) || !meta?.pathTemplate || (meta.idPattern && !new RegExp(meta.idPattern).test(id)))
        return undefined
    return `${host.replace(/\/+$/, '')}/project/${projectId}${meta.pathTemplate.replace('{id}', encodeURIComponent(id))}`
}
export function objectMeta(kind: string): string {
    const meta = kinds[kind]
    return meta ? `${meta.kindLabel} · ${meta.source}` : kind
}
export function objectTagsPlugin(md: MarkdownIt): void {
    md.core.ruler.before('block', 'object_cards_reset', (state) => {
        state.env.objectCards = 0
    })
    md.block.ruler.before(
        'html_block',
        'object_card',
        (state, startLine, endLine, silent) => {
            if ((state.sCount[startLine] ?? 0) - state.blkIndent >= 4) return false
            const start = (state.bMarks[startLine] ?? 0) + (state.tShift[startLine] ?? 0)
            const tag = matchTag(state.src.slice(start))
            if (!tag || tag.attrs.display !== 'block') return false
            const end = start + tag.raw.length
            let line = startLine
            while (line < endLine && (state.eMarks[line] ?? state.src.length) < end) line++
            if (line >= endLine || !/^[ \t]*$/.test(state.src.slice(end, state.eMarks[line]))) return false
            const title = tag.attrs.title?.trim() || undefined
            const spec: ObjectCardSpec | undefined =
                tag.kind === 'insight' && tag.attrs.id?.trim()
                    ? { mode: 'insight', shortId: tag.attrs.id.trim(), title }
                    : tag.kind === 'hogql' && tag.body?.trim()
                      ? { mode: 'hogql', query: tag.body.trim(), title }
                      : undefined
            if (!spec || state.env.objectCards >= 10) return false
            if (silent) return true
            state.env.objectCards++
            const token = state.push('object_card', '', 0)
            token.meta = spec
            token.block = true
            state.line = line + 1
            return true
        },
        { alt: ['paragraph', 'reference', 'blockquote', 'list'] }
    )
    md.inline.ruler.before('html_inline', 'object_ref', (state, silent) => {
        const src = state.src.slice(state.pos)
        if (!src.startsWith('<')) return false
        const tag = matchTag(src)
        const partial = !tag && unfinished(src)
        const markup = /^<\/?([a-z][\w-]*)[^>]*>/.exec(src)
        const hiddenMarkup = !partial && markup && objectKind(markup[1] ?? '') ? markup[0] : undefined
        if (!tag && !hiddenMarkup && !partial) return false
        if (!silent) {
            const ref = tag && objectRef(tag)
            const token = state.push(ref ? 'object_ref' : 'text', '', 0)
            token.meta = ref
            token.content = ref ? ref.label : tag && !tag.kind ? tag.body?.trim() || tag.attrs.label?.trim() || '' : ''
        }
        state.pos += tag?.raw.length ?? hiddenMarkup?.length ?? src.length
        return true
    })
}
