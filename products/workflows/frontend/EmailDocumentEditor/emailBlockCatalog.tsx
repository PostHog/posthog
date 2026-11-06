import type { JSONContent } from '@tiptap/core'

import { IconButton, IconCode, IconColumns, IconImage, IconList, IconMinus, IconQuote } from '@posthog/icons'

import { IconTextSize } from 'lib/lemon-ui/icons'

import { EMPTY_COLUMN, UNSUBSCRIBE_LINE } from './emailCommands'

export interface EmailBlockOption {
    key: string
    title: string
    detail: string
    icon: JSX.Element
    keywords: string
    /** Text blocks convert the current line. The rest are inserted as new blocks. */
    content?: JSONContent
    needsImage?: boolean
}

const twoColumns: JSONContent = { type: 'emailColumns', content: [EMPTY_COLUMN, EMPTY_COLUMN] }

export const EMAIL_BLOCK_OPTIONS: EmailBlockOption[] = [
    {
        key: 'paragraph',
        title: 'Text',
        detail: 'A paragraph of text',
        icon: <IconTextSize />,
        keywords: 'text paragraph body',
        content: { type: 'paragraph' },
    },
    {
        key: 'heading1',
        title: 'Heading 1',
        detail: 'The largest heading',
        icon: <IconTextSize />,
        keywords: 'h1 title heading',
        content: { type: 'heading', attrs: { level: 1 } },
    },
    {
        key: 'heading2',
        title: 'Heading 2',
        detail: 'A section heading',
        icon: <IconTextSize />,
        keywords: 'h2 subtitle heading',
        content: { type: 'heading', attrs: { level: 2 } },
    },
    {
        key: 'heading3',
        title: 'Heading 3',
        detail: 'A small heading',
        icon: <IconTextSize />,
        keywords: 'h3 heading',
        content: { type: 'heading', attrs: { level: 3 } },
    },
    {
        key: 'image',
        title: 'Image',
        detail: 'Upload or link an image',
        icon: <IconImage />,
        keywords: 'image picture photo logo banner',
        needsImage: true,
    },
    {
        key: 'button',
        title: 'Button',
        detail: 'A link styled as a button',
        icon: <IconButton />,
        keywords: 'button cta link action',
        content: { type: 'emailButton', attrs: { href: '' }, content: [{ type: 'text', text: 'Button' }] },
    },
    {
        key: 'columns',
        title: 'Columns',
        detail: 'Side by side content that stacks on phones',
        icon: <IconColumns />,
        keywords: 'columns layout grid section side',
        content: twoColumns,
    },
    {
        key: 'divider',
        title: 'Divider',
        detail: 'A horizontal line',
        icon: <IconMinus />,
        keywords: 'divider hr line rule separator',
        content: { type: 'horizontalRule' },
    },
    {
        key: 'spacer',
        title: 'Spacer',
        detail: 'Empty vertical space',
        icon: <IconMinus />,
        keywords: 'spacer space gap',
        content: { type: 'emailSpacer', attrs: { height: 24 } },
    },
    {
        key: 'bulletList',
        title: 'Bullet list',
        detail: 'A list with bullets',
        icon: <IconList />,
        keywords: 'ul bullet list unordered',
        content: { type: 'bulletList', content: [{ type: 'listItem', content: [{ type: 'paragraph' }] }] },
    },
    {
        key: 'orderedList',
        title: 'Numbered list',
        detail: 'A list with numbers',
        icon: <IconList />,
        keywords: 'ol ordered numbered list',
        content: { type: 'orderedList', content: [{ type: 'listItem', content: [{ type: 'paragraph' }] }] },
    },
    {
        key: 'quote',
        title: 'Quote',
        detail: 'An indented quote',
        icon: <IconQuote />,
        keywords: 'quote blockquote',
        content: { type: 'blockquote', content: [{ type: 'paragraph' }] },
    },
    {
        key: 'html',
        title: 'Custom HTML',
        detail: 'Paste your own HTML',
        icon: <IconCode />,
        keywords: 'html code custom raw',
        content: { type: 'emailHtml', attrs: { html: '' } },
    },
    {
        key: 'unsubscribe',
        title: 'Unsubscribe link',
        detail: 'A line with the recipient’s unsubscribe link',
        icon: <IconMinus />,
        keywords: 'unsubscribe footer opt out',
        content: UNSUBSCRIBE_LINE,
    },
]
