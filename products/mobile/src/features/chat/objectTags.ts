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
/**
 * Bounds each scan that starts at a `<`: an attribute value, a tag body, and the search for a close tag.
 * Without it, every `<` in a reply can rescan to the end of the text, and a crafted reply costs O(n^2).
 * With it, a reply costs at most O(n * MAX_TAG_LENGTH). A tag that goes past the bound is not an object.
 */
const MAX_TAG_LENGTH = 8192
const OPEN = new RegExp(`<([a-z][\\w-]*)((?:\\s+[a-z][\\w-]*\\s*=\\s*"[^"]{0,${MAX_TAG_LENGTH}}")*)\\s*(\\/?)>`, 'y')
const HEAD = /<\/?([a-z][\w-]*)/y
const PART = new RegExp(`\\s+|[a-z][\\w-]*|=|"[^"]{0,${MAX_TAG_LENGTH}}"|"[^"]{0,${MAX_TAG_LENGTH}}$|\\/$`, 'y')
export function objectKind(name: string): string | undefined {
    return kinds[name] ? name : aliases[name]
}
function decode(value: string): string {
    return value.replace(
        /&(amp|lt|gt|quot|apos);/g,
        (_, key: string) => ({ amp: '&', lt: '<', gt: '>', quot: '"', apos: "'" })[key] ?? ''
    )
}
function closeTag(name: string): RegExp {
    return new RegExp(`([\\s\\S]{0,${MAX_TAG_LENGTH}}?)</${name}\\s*>`, 'y')
}
function matchTag(
    src: string,
    pos: number
): { raw: string; kind?: string; attrs: Record<string, string>; body?: string } | undefined {
    OPEN.lastIndex = pos
    const open = OPEN.exec(src)
    if (!open) return undefined
    const attrs: Record<string, string> = {}
    for (const attr of (open[2] ?? '').matchAll(/([a-z][\w-]*)\s*=\s*"([^"]*)"/g))
        attrs[attr[1] ?? ''] = decode(attr[2] ?? '')
    const name = open[1] ?? ''
    const kind = objectKind(name)
    if (!kind && !('id' in attrs)) return undefined
    if (open[3]) return { raw: open[0], kind, attrs }
    const close = closeTag(name)
    close.lastIndex = OPEN.lastIndex
    const body = close.exec(src)
    return body ? { raw: open[0] + body[0], kind, attrs, body: body[1] } : undefined
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
function knownName(src: string, pos: number): string | undefined {
    HEAD.lastIndex = pos
    const name = HEAD.exec(src)?.[1]
    return name && objectKind(name) ? name : undefined
}
function unfinished(src: string, pos: number): boolean {
    const name = src.charCodeAt(pos + 1) === 0x2f ? undefined : knownName(src, pos)
    if (!name) return false
    OPEN.lastIndex = pos
    const open = OPEN.exec(src)
    if (open && !open[3]) {
        const close = closeTag(name)
        close.lastIndex = pos
        return !close.test(src)
    }
    PART.lastIndex = pos + 1 + name.length
    while (PART.lastIndex < src.length) {
        if (PART.lastIndex - pos > MAX_TAG_LENGTH || !PART.exec(src)) return false
    }
    return true
}
interface BracketScan {
    src: string
    from: number
    at: number
}
/** Keeps the first `>` at or after `from`, so that a run of `<` with no `>` scans the text once per parse. */
function nextBracket(scan: BracketScan, src: string, pos: number): number {
    if (scan.src !== src || pos < scan.from || (scan.at !== -1 && scan.at < pos)) {
        scan.src = src
        scan.at = src.indexOf('>', pos)
    }
    scan.from = pos
    return scan.at
}
function hiddenMarkup(scan: BracketScan, src: string, pos: number): string | undefined {
    if (!knownName(src, pos)) return undefined
    const end = nextBracket(scan, src, pos)
    return end !== -1 && end - pos <= MAX_TAG_LENGTH ? src.slice(pos, end + 1) : undefined
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
            if (state.src.charCodeAt(start) !== 0x3c) return false
            const tag = matchTag(state.src, start)
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
        if (state.src.charCodeAt(state.pos) !== 0x3c) return false
        const tag = matchTag(state.src, state.pos)
        const partial = !tag && unfinished(state.src, state.pos)
        state.env.objectBracketScan ??= { src: '', from: 0, at: -1 } satisfies BracketScan
        const markup = tag || partial ? undefined : hiddenMarkup(state.env.objectBracketScan, state.src, state.pos)
        if (!tag && !markup && !partial) return false
        if (!silent) {
            const ref = tag && objectRef(tag)
            const token = state.push(ref ? 'object_ref' : 'text', '', 0)
            token.meta = ref
            token.content = ref ? ref.label : tag && !tag.kind ? tag.body?.trim() || tag.attrs.label?.trim() || '' : ''
        }
        state.pos = tag ? state.pos + tag.raw.length : markup ? state.pos + markup.length : state.src.length
        return true
    })
}
