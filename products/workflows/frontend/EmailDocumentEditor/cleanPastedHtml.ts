const REMOVED_ELEMENTS = 'style, meta, link, script, title, head, xml, o\\:smarttagtype, svg, noscript, iframe, object'
const KEPT_ATTRIBUTES: Record<string, string[]> = { A: ['href'], IMG: ['src', 'alt', 'width'] }
const BOLD_WEIGHT = /^(bold|bolder|[6-9]00)$/i
const WORD_LIST = /mso-list:\s*l(\d+)\s+level(\d+)/i
const ORDERED_MARKER = /^\s*(\d+|[a-z]+)[.)]/i

function wrapChildrenIn(element: Element, tag: string): void {
    const wrapper = element.ownerDocument.createElement(tag)
    while (element.firstChild) {
        wrapper.appendChild(element.firstChild)
    }
    element.appendChild(wrapper)
}

function unwrap(element: Element): void {
    element.replaceWith(...Array.from(element.childNodes))
}

function removeComments(doc: Document): void {
    const walker = doc.createTreeWalker(doc, NodeFilter.SHOW_COMMENT)
    const comments: Node[] = []
    while (walker.nextNode()) {
        comments.push(walker.currentNode)
    }
    comments.forEach((comment) => comment.parentNode?.removeChild(comment))
}

/** Word and Google Docs write formatting as inline styles on spans, which the editor wouldn't otherwise read. */
function styleToTags(element: HTMLElement): void {
    const { fontWeight, fontStyle, textDecoration, textDecorationLine } = element.style
    const decoration = `${textDecoration} ${textDecorationLine}`
    if (element.tagName === 'SPAN' || element.tagName === 'FONT') {
        if (BOLD_WEIGHT.test(fontWeight)) {
            wrapChildrenIn(element, 'strong')
        }
        if (fontStyle === 'italic') {
            wrapChildrenIn(element, 'em')
        }
        if (decoration.includes('underline')) {
            wrapChildrenIn(element, 'u')
        }
        if (decoration.includes('line-through')) {
            wrapChildrenIn(element, 's')
        }
    }
}

function wordListItem(paragraph: HTMLElement): { listId: string; level: number; ordered: boolean } | null {
    const match = (paragraph.getAttribute('style') ?? '').match(WORD_LIST)
    if (!match) {
        return null
    }
    const marker = paragraph.querySelector('[style*="mso-list:Ignore" i], [style*="mso-list: Ignore" i]')
    const markerText = marker?.textContent ?? ''
    marker?.remove()
    return { listId: match[1], level: Number(match[2]), ordered: ORDERED_MARKER.test(markerText) }
}

/** Word pastes a list as paragraphs with its bullet as literal text, so the real list has to be rebuilt. */
function rebuildWordLists(body: HTMLElement): void {
    const paragraphs = Array.from(body.querySelectorAll<HTMLElement>('p, h1, h2, h3'))
    let stack: { level: number; list: HTMLElement }[] = []
    let previous: HTMLElement | null = null
    let currentListId: string | null = null

    for (const paragraph of paragraphs) {
        const item = wordListItem(paragraph)
        if (!item) {
            continue
        }
        const contiguous = previous && previous.nextElementSibling === paragraph
        if (!contiguous || item.listId !== currentListId) {
            stack = []
        }
        currentListId = item.listId
        previous = paragraph
        const li = paragraph.ownerDocument.createElement('li')
        li.innerHTML = paragraph.innerHTML
        while (stack.length && stack[stack.length - 1].level > item.level) {
            stack.pop()
        }
        if (!stack.length || stack[stack.length - 1].level < item.level) {
            const list = paragraph.ownerDocument.createElement(item.ordered ? 'ol' : 'ul')
            if (stack.length) {
                stack[stack.length - 1].list.lastElementChild?.appendChild(list)
            } else {
                paragraph.before(list)
            }
            stack.push({ level: item.level, list })
        }
        stack[stack.length - 1].list.appendChild(li)
        // Keeps the next paragraph contiguous: it now follows this placeholder rather than the list.
        const placeholder = paragraph.ownerDocument.createElement('span')
        placeholder.setAttribute('data-word-list-placeholder', '')
        paragraph.replaceWith(placeholder)
        previous = placeholder
    }
    body.querySelectorAll('[data-word-list-placeholder]').forEach((placeholder) => placeholder.remove())
}

function isBlankBlock(element: Element): boolean {
    return (
        ['P', 'DIV'].includes(element.tagName) &&
        !element.querySelector('img') &&
        (element.textContent ?? '').replace(/[\s ]/g, '') === ''
    )
}

export interface CleanedPaste {
    html: string
    droppedImages: number
}

/**
 * Reduces HTML from Word, Google Docs and web pages to its structure and basic formatting, so a paste takes on the
 * email's own styles rather than bringing in fonts, colors and layout that don't belong to it.
 */
export function cleanPastedHtml(html: string): CleanedPaste {
    // Copied from this editor, so it's already clean and its block styles should survive. Other ProseMirror apps
    // also mark their copies with data-pm-slice, so the email's own attributes have to be there too.
    if (html.includes('data-pm-slice') && /data-email-(style|button|spacer|html|columns?|variable)\b/.test(html)) {
        return { html, droppedImages: 0 }
    }

    const doc = new DOMParser().parseFromString(html, 'text/html')
    const body = doc.body
    removeComments(doc)
    doc.querySelectorAll(REMOVED_ELEMENTS).forEach((element) => element.remove())
    // <o:p> is Word's empty end of paragraph marker. DOMParser reads the tag name with its namespace prefix.
    Array.from(body.querySelectorAll('*'))
        .filter((element) => element.tagName.includes(':'))
        .forEach(unwrap)

    rebuildWordLists(body)

    // Google Docs wraps the whole paste in a <b> that isn't bold.
    body.querySelectorAll<HTMLElement>('b[id^="docs-internal-guid"]').forEach(unwrap)
    body.querySelectorAll<HTMLElement>('b').forEach((element) => {
        if (element.style.fontWeight === 'normal') {
            unwrap(element)
        }
    })

    body.querySelectorAll<HTMLElement>('.MsoTitle').forEach((element) => {
        const heading = doc.createElement('h1')
        heading.innerHTML = element.innerHTML
        element.replaceWith(heading)
    })
    body.querySelectorAll<HTMLElement>('.MsoSubtitle').forEach((element) => {
        const heading = doc.createElement('h2')
        heading.innerHTML = element.innerHTML
        element.replaceWith(heading)
    })
    body.querySelectorAll<HTMLElement>('h4, h5, h6').forEach((element) => {
        const heading = doc.createElement('h3')
        heading.innerHTML = element.innerHTML
        element.replaceWith(heading)
    })

    body.querySelectorAll<HTMLElement>('*').forEach(styleToTags)

    let droppedImages = 0
    body.querySelectorAll('img').forEach((image) => {
        const src = image.getAttribute('src') ?? ''
        // Inline data and local files from Word can't be sent. Hosted images are kept.
        if (!/^https?:/i.test(src)) {
            droppedImages += 1
            image.remove()
        }
    })

    body.querySelectorAll('*').forEach((element) => {
        const kept = KEPT_ATTRIBUTES[element.tagName] ?? []
        Array.from(element.attributes).forEach((attribute) => {
            if (!kept.includes(attribute.name.toLowerCase())) {
                element.removeAttribute(attribute.name)
            }
        })
    })

    body.querySelectorAll('span, font').forEach(unwrap)
    // A table on a web page is layout, and email tables are the editor's job. Its cells become plain blocks.
    body.querySelectorAll('td, th').forEach((cell) => {
        if (!cell.querySelector('p, div, h1, h2, h3, ul, ol, table, img')) {
            wrapChildrenIn(cell, 'p')
        }
    })
    body.querySelectorAll('table, thead, tbody, tfoot, tr, td, th, caption, colgroup').forEach(unwrap)
    // Docs puts a line break between blocks for spacing, which a block's own padding replaces.
    Array.from(body.children)
        .filter((element) => element.tagName === 'BR')
        .forEach((element) => element.remove())
    body.querySelectorAll('a:not([href])').forEach(unwrap)
    // A list item holds a paragraph in Docs. Word leaves blank paragraphs as spacing, which a block's own padding replaces.
    Array.from(body.querySelectorAll('p, div'))
        .filter(isBlankBlock)
        .forEach((element) => element.remove())

    return { html: body.innerHTML, droppedImages }
}
