import { Extension, InputRule, Node, PasteRule, mergeAttributes } from '@tiptap/core'
import { Color } from '@tiptap/extension-color'
import { Document } from '@tiptap/extension-document'
import { TextStyle } from '@tiptap/extension-text-style'
import { Placeholder } from '@tiptap/extensions'
import { ReactNodeViewRenderer } from '@tiptap/react'
import StarterKit from '@tiptap/starter-kit'

import { LinkExtension } from 'lib/components/RichContentEditor/LinkExtension'

import { EmailHtmlBlockView } from './components/EmailHtmlBlockView'
import { EmailImageBlockView } from './components/EmailImageBlockView'
import { EmailVariableChip } from './components/EmailVariableChip'
import { EmailBlockStyle } from './emailDocument'
import { parseLiquidOutput } from './emailVariables'
import { safeColor, safeEmailLink, safeEmailStyle } from './renderEmailHtml'

const COLUMN_BLOCKS =
    '(paragraph | heading | bulletList | orderedList | blockquote | horizontalRule | emailImage | emailButton | emailSpacer | emailHtml)+'
const STYLED_BLOCKS = [
    'paragraph',
    'bulletList',
    'orderedList',
    'blockquote',
    'horizontalRule',
    'emailImage',
    'emailButton',
    'emailColumns',
    'emailColumn',
    'emailHtml',
]

function sidesCss(sides: EmailBlockStyle['padding']): string | undefined {
    return sides ? `${sides.top}px ${sides.right}px ${sides.bottom}px ${sides.left}px` : undefined
}

/** How a block's style looks on the canvas. The email itself comes from `renderEmailHtml`. */
export function blockStyleToCanvasCss(rawStyle: EmailBlockStyle | null | undefined, typeName: string): string {
    const style = safeEmailStyle(rawStyle)
    if (!style) {
        return ''
    }
    const isButton = typeName === 'emailButton'
    const isImage = typeName === 'emailImage'
    const isDivider = typeName === 'horizontalRule'
    const isList = typeName === 'bulletList' || typeName === 'orderedList'
    const properties: Record<string, string | undefined> = {
        color: isButton ? undefined : style.color,
        'background-color': isButton ? undefined : style.backgroundColor,
        'font-family': !isButton ? style.fontFamily : undefined,
        'font-weight': !isButton && style.fontWeight ? String(style.fontWeight) : undefined,
        'font-size': !isButton && style.fontSize ? `${style.fontSize}px` : undefined,
        'line-height': !isButton && style.lineHeight ? `${style.lineHeight}%` : undefined,
        'letter-spacing': !isButton && style.letterSpacing ? `${style.letterSpacing}px` : undefined,
        'text-transform': !isButton && style.uppercase ? 'uppercase' : undefined,
        'text-align': style.textAlign,
        padding: sidesCss(style.padding),
        'padding-left': isList ? `${(style.padding?.left ?? 0) + (style.listIndent ?? 24)}px` : undefined,
        gap: style.columnGap !== undefined ? `${style.columnGap}px` : undefined,
        '--email-list-gap': style.listItemGap !== undefined ? `${style.listItemGap}px` : undefined,
        '--email-link': style.linkColor,
        '--email-link-decoration': style.linkUnderline === false ? 'none' : undefined,
        'border-radius': !isButton && !isImage && style.borderRadius ? `${style.borderRadius}px` : undefined,
        border:
            !isButton && !isImage && !isDivider && style.borderWidth
                ? `${style.borderWidth}px solid ${style.borderColor ?? '#e5e5e5'}`
                : undefined,
    }
    return Object.entries(properties)
        .filter(([, value]) => value !== undefined && value !== '')
        .map(([key, value]) => `${key}:${value}`)
        .join(';')
}

function emailStyleAttribute(keepOnSplit: boolean): Record<string, any> {
    return {
        emailStyle: {
            default: null,
            keepOnSplit,
            parseHTML: (element: HTMLElement) => {
                const raw = element.getAttribute('data-email-style')
                try {
                    return raw ? safeEmailStyle(JSON.parse(raw)) : null
                } catch {
                    return null
                }
            },
            renderHTML: (attributes: Record<string, any>) =>
                attributes.emailStyle ? { 'data-email-style': JSON.stringify(attributes.emailStyle) } : {},
        },
    }
}

export const EmailBlockStyleExtension = Extension.create({
    name: 'emailBlockStyle',
    addGlobalAttributes() {
        return [
            { types: STYLED_BLOCKS, attributes: emailStyleAttribute(true) },
            // Enter after a heading starts a normal paragraph, which shouldn't take on the heading's size or spacing.
            { types: ['heading'], attributes: emailStyleAttribute(false) },
        ]
    },
})

function styledAttributes(node: { attrs: Record<string, any>; type: { name: string } }): Record<string, string> {
    const css = blockStyleToCanvasCss(node.attrs.emailStyle, node.type.name)
    return css ? { style: css } : {}
}

/** Adds the block's style to its canvas element. Global attributes can't, because they don't see the node type. */
function withCanvasStyle<T extends Node<any, any>>(extension: T): T {
    return extension.extend({
        renderHTML(this: any, props: any) {
            const rendered = this.parent?.(props)
            if (!Array.isArray(rendered)) {
                return rendered
            }
            const [tag, attributes, ...rest] = rendered
            const hasAttributes = attributes && typeof attributes === 'object' && !Array.isArray(attributes)
            return [
                tag,
                mergeAttributes(hasAttributes ? attributes : {}, styledAttributes(props.node)),
                ...(hasAttributes ? rest : [attributes, ...rest].filter((part) => part !== undefined)),
            ]
        },
    }) as T
}

const EmailDocumentNode = Document.extend({
    addAttributes() {
        return { page: { default: {} } }
    },
})

export const EmailButton = Node.create({
    name: 'emailButton',
    group: 'block',
    content: 'inline*',
    defining: true,
    addAttributes() {
        return {
            href: {
                default: '',
                parseHTML: (element) => element.getAttribute('data-href') ?? '',
                renderHTML: (attributes) => ({ 'data-href': attributes.href }),
            },
        }
    },
    parseHTML() {
        return [{ tag: 'div[data-email-button]', contentElement: 'span' }]
    },
    renderHTML({ node, HTMLAttributes }) {
        const style = safeEmailStyle(node.attrs.emailStyle) ?? {}
        const buttonCss = [
            style.backgroundColor ? `background-color:${style.backgroundColor}` : '',
            style.color ? `color:${style.color}` : '',
            style.borderRadius !== undefined ? `border-radius:${style.borderRadius}px` : '',
            style.fontSize ? `font-size:${style.fontSize}px` : '',
            style.fontFamily ? `font-family:${style.fontFamily}` : '',
            style.fontWeight ? `font-weight:${style.fontWeight}` : '',
            style.buttonWidth ? `width:${Math.min(style.buttonWidth, 100)}%;box-sizing:border-box` : '',
            style.borderWidth ? `border:${style.borderWidth}px solid ${style.borderColor ?? 'transparent'}` : '',
            style.innerPaddingX !== undefined || style.innerPaddingY !== undefined
                ? `padding:${style.innerPaddingY ?? 12}px ${style.innerPaddingX ?? 24}px`
                : '',
        ]
            .filter(Boolean)
            .join(';')
        return [
            'div',
            mergeAttributes(HTMLAttributes, { 'data-email-button': '', class: 'email-canvas-button-row' }),
            ['span', { class: 'email-canvas-button', style: buttonCss }, 0],
        ]
    },
    addKeyboardShortcuts() {
        return {
            Enter: () => {
                if (!this.editor.isActive('emailButton')) {
                    return false
                }
                // A button label is one line, so Enter moves on to the next block instead of breaking the button.
                const { $from } = this.editor.state.selection
                return this.editor
                    .chain()
                    .insertContentAt($from.after(), { type: 'paragraph' })
                    .setTextSelection($from.after() + 1)
                    .run()
            },
        }
    },
})

export const EmailImage = Node.create({
    name: 'emailImage',
    group: 'block',
    atom: true,
    draggable: true,
    selectable: true,
    addAttributes() {
        return {
            src: { default: '' },
            alt: { default: '' },
            href: { default: '' },
            naturalWidth: { default: null },
            naturalHeight: { default: null },
            mediaId: { default: null },
        }
    },
    parseHTML() {
        return [
            {
                tag: 'img[src]',
                getAttrs: (element) =>
                    /^(https?:|\/)/i.test(element.getAttribute('src') ?? '') ? null : (false as const),
            },
        ]
    },
    renderHTML({ HTMLAttributes }) {
        return ['img', mergeAttributes(HTMLAttributes)]
    },
    addNodeView() {
        return ReactNodeViewRenderer(EmailImageBlockView)
    },
})

export const EmailSpacer = Node.create({
    name: 'emailSpacer',
    group: 'block',
    atom: true,
    draggable: true,
    selectable: true,
    addAttributes() {
        return {
            height: {
                default: 24,
                parseHTML: (element) => Number(element.getAttribute('data-height')) || 24,
                renderHTML: (attributes) => ({ 'data-height': attributes.height }),
            },
            backgroundColor: {
                default: null,
                parseHTML: (element) => safeColor(element.getAttribute('data-background-color')) || null,
                renderHTML: (attributes) =>
                    attributes.backgroundColor ? { 'data-background-color': attributes.backgroundColor } : {},
            },
        }
    },
    parseHTML() {
        return [{ tag: 'div[data-email-spacer]' }]
    },
    renderHTML({ node, HTMLAttributes }) {
        return [
            'div',
            mergeAttributes(HTMLAttributes, {
                'data-email-spacer': '',
                class: 'email-canvas-spacer',
                style: `height:${Number(node.attrs.height) || 0}px${
                    safeColor(node.attrs.backgroundColor)
                        ? `;background-color:${safeColor(node.attrs.backgroundColor)}`
                        : ''
                }`,
            }),
        ]
    },
})

export const EmailHtmlBlock = Node.create({
    name: 'emailHtml',
    group: 'block',
    atom: true,
    draggable: true,
    selectable: true,
    addAttributes() {
        return {
            html: {
                default: '',
                parseHTML: (element) => element.getAttribute('data-html') ?? '',
                renderHTML: (attributes) => ({ 'data-html': attributes.html }),
            },
        }
    },
    parseHTML() {
        return [{ tag: 'div[data-email-html]' }]
    },
    renderHTML({ HTMLAttributes }) {
        return ['div', mergeAttributes(HTMLAttributes, { 'data-email-html': '' })]
    },
    addNodeView() {
        return ReactNodeViewRenderer(EmailHtmlBlockView)
    },
})

export const EmailColumn = Node.create({
    name: 'emailColumn',
    content: COLUMN_BLOCKS,
    isolating: true,
    defining: true,
    // A click in a column's empty space should place the cursor, not select the column for Backspace to delete.
    selectable: false,
    addAttributes() {
        return {
            ratio: {
                default: 1,
                parseHTML: (element) => Number(element.getAttribute('data-ratio')) || 1,
                renderHTML: (attributes) => ({ 'data-ratio': attributes.ratio }),
            },
        }
    },
    parseHTML() {
        return [{ tag: 'div[data-email-column]' }]
    },
    renderHTML({ node, HTMLAttributes }) {
        return [
            'div',
            mergeAttributes(HTMLAttributes, {
                'data-email-column': '',
                class: 'email-canvas-column',
                style: `flex:${node.attrs.ratio} 1 0;${blockStyleToCanvasCss(node.attrs.emailStyle, 'emailColumn')}`,
            }),
            0,
        ]
    },
})

export const EmailColumns = Node.create({
    name: 'emailColumns',
    group: 'block',
    content: 'emailColumn{1,4}',
    isolating: true,
    defining: true,
    draggable: true,
    parseHTML() {
        return [{ tag: 'div[data-email-columns]' }]
    },
    renderHTML({ HTMLAttributes }) {
        return ['div', mergeAttributes(HTMLAttributes, { 'data-email-columns': '', class: 'email-canvas-columns' }), 0]
    },
})

// Finds `{{ … }}`. `}` can't appear inside, which also keeps a typed `{% … %}` out of it. A tag with Liquid's
// whitespace trimming (`{{- … -}}`) stays text, since a chip can't write the hyphens back.
const VARIABLE_INPUT = /\{\{(?!-)([^{}]*[^{}-])\}\}$/
const VARIABLE_PASTE = /\{\{(?!-)([^{}]*[^{}-])\}\}/g

export const EmailVariable = Node.create({
    name: 'variable',
    group: 'inline',
    inline: true,
    atom: true,
    selectable: true,
    addAttributes() {
        return {
            expression: {
                default: '',
                parseHTML: (element) => element.getAttribute('data-expression') ?? '',
                renderHTML: (attributes) => ({ 'data-expression': attributes.expression }),
            },
            fallback: {
                default: '',
                parseHTML: (element) => element.getAttribute('data-fallback') ?? '',
                renderHTML: (attributes) => ({ 'data-fallback': attributes.fallback }),
            },
        }
    },
    parseHTML() {
        return [{ tag: 'span[data-email-variable]' }]
    },
    renderHTML({ node, HTMLAttributes }) {
        return [
            'span',
            mergeAttributes(HTMLAttributes, { 'data-email-variable': '' }),
            `{{ ${node.attrs.expression} }}`,
        ]
    },
    renderText({ node }) {
        return `{{ ${node.attrs.expression} }}`
    },
    addNodeView() {
        return ReactNodeViewRenderer(EmailVariableChip)
    },
    // Written by hand because the stock node rules replace only the capture group, which would leave the braces behind.
    addInputRules() {
        return [
            new InputRule({
                find: VARIABLE_INPUT,
                handler: ({ state, range, match }) => {
                    state.tr.replaceWith(range.from, range.to, this.type.create(parseLiquidOutput(match[1])))
                },
            }),
        ]
    },
    addPasteRules() {
        return [
            new PasteRule({
                find: VARIABLE_PASTE,
                handler: ({ state, range, match }) => {
                    state.tr.replaceWith(range.from, range.to, this.type.create(parseLiquidOutput(match[1])))
                },
            }),
        ]
    },
})

/** Liquid links like `{{ unsubscribe_url }}` aren't valid URLs, but they are what people put here. */
export const EmailLink = LinkExtension.extend({
    inclusive: false,
    addAttributes() {
        return {
            ...this.parent?.(),
            underline: {
                default: null,
                parseHTML: (element: HTMLElement) => (/\bnone\b/.test(element.style.textDecoration) ? false : null),
                renderHTML: (attributes: Record<string, any>) =>
                    attributes.underline === false ? { style: 'text-decoration:none' } : {},
            },
            color: {
                default: null,
                parseHTML: (element: HTMLElement) => element.style.color || null,
                renderHTML: (attributes: Record<string, any>) =>
                    attributes.color ? { style: `color:${attributes.color}` } : {},
            },
        }
    },
    addOptions() {
        return {
            ...this.parent?.(),
            openOnClick: false,
            autolink: true,
            linkOnPaste: true,
            HTMLAttributes: { target: '_blank', rel: 'noopener noreferrer nofollow', class: null },
            isAllowedUri: (url: string | undefined) => !!safeEmailLink(url),
        } as any
    },
})

export const EmailTextStyle = TextStyle.extend({
    addAttributes() {
        return {
            ...this.parent?.(),
            fontSize: {
                default: null,
                parseHTML: (element: HTMLElement) => parseInt(element.style.fontSize, 10) || null,
                renderHTML: (attributes: Record<string, any>) =>
                    attributes.fontSize ? { style: `font-size:${attributes.fontSize}px` } : {},
            },
            fontFamily: {
                default: null,
                parseHTML: (element: HTMLElement) => element.style.fontFamily || null,
                renderHTML: (attributes: Record<string, any>) =>
                    attributes.fontFamily ? { style: `font-family:${attributes.fontFamily}` } : {},
            },
            letterSpacing: {
                default: null,
                parseHTML: (element: HTMLElement) => element.style.letterSpacing || null,
                renderHTML: (attributes: Record<string, any>) =>
                    attributes.letterSpacing ? { style: `letter-spacing:${attributes.letterSpacing}` } : {},
            },
            lineHeight: {
                default: null,
                parseHTML: (element: HTMLElement) => element.style.lineHeight || null,
                renderHTML: (attributes: Record<string, any>) =>
                    attributes.lineHeight ? { style: `line-height:${attributes.lineHeight}` } : {},
            },
            highlight: {
                default: null,
                parseHTML: (element: HTMLElement) => element.style.backgroundColor || null,
                renderHTML: (attributes: Record<string, any>) =>
                    attributes.highlight ? { style: `background-color:${attributes.highlight}` } : {},
            },
            textTransform: {
                default: null,
                parseHTML: (element: HTMLElement) => element.style.textTransform || null,
                renderHTML: (attributes: Record<string, any>) =>
                    attributes.textTransform ? { style: `text-transform:${attributes.textTransform}` } : {},
            },
        }
    },
})

/** The schema without the editor's interactive parts, so a document can be built or validated outside of one. */
export const emailSchemaExtensions = [
    EmailDocumentNode,
    withCanvasStyle(EmailButton),
    EmailImage,
    EmailSpacer,
    EmailHtmlBlock,
    EmailColumn,
    withCanvasStyle(EmailColumns),
    EmailVariable,
    EmailLink,
    EmailTextStyle,
    Color,
    EmailBlockStyleExtension,
]

export function buildEmailExtensions(placeholder: string): any[] {
    return [
        StarterKit.configure({
            document: false,
            link: false,
            heading: { levels: [1, 2, 3] },
            codeBlock: false,
            trailingNode: { node: 'paragraph', notAfter: ['paragraph'] },
            dropcursor: { color: false, width: 3, class: 'EmailDropCursor' },
        }).extend({
            addExtensions(this: any) {
                return (this.parent?.() ?? []).map((extension: any) =>
                    ['paragraph', 'heading', 'bulletList', 'orderedList', 'blockquote', 'horizontalRule'].includes(
                        extension.name
                    )
                        ? withCanvasStyle(extension)
                        : extension
                )
            },
        }),
        ...emailSchemaExtensions,
        Placeholder.configure({
            placeholder: ({ editor, node, pos }) => {
                if (node.type.name !== 'paragraph') {
                    return ''
                }
                const $pos = editor.state.doc.resolve(pos)
                return $pos.depth > 0 && $pos.node($pos.depth).type.name === 'emailColumn'
                    ? 'Type / for blocks'
                    : placeholder
            },
            includeChildren: true,
        }),
    ]
}
