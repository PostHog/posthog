import type { Editor } from '@tiptap/core'
import { forwardRef } from 'react'

import { IconCode, IconList } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { IconBold, IconItalic } from 'lib/lemon-ui/icons'

const MARKS: { name: string; label: string; content: JSX.Element; run: (editor: Editor) => void }[] = [
    { name: 'bold', label: 'Bold', content: <IconBold />, run: (editor) => editor.chain().focus().toggleBold().run() },
    {
        name: 'italic',
        label: 'Italic',
        content: <IconItalic />,
        run: (editor) => editor.chain().focus().toggleItalic().run(),
    },
    {
        name: 'underline',
        label: 'Underline',
        content: <span className="underline text-sm leading-none">U</span>,
        run: (editor) => editor.chain().focus().toggleUnderline().run(),
    },
    {
        name: 'strike',
        label: 'Strikethrough',
        content: <span className="line-through text-sm leading-none">S</span>,
        run: (editor) => editor.chain().focus().toggleStrike().run(),
    },
    { name: 'code', label: 'Code', content: <IconCode />, run: (editor) => editor.chain().focus().toggleCode().run() },
]

const LISTS: typeof MARKS = [
    {
        name: 'bulletList',
        label: 'Bullet list',
        content: <IconList />,
        run: (editor) => editor.chain().focus().toggleBulletList().run(),
    },
    {
        name: 'orderedList',
        label: 'Numbered list',
        content: <span className="text-xs leading-none">1.</span>,
        run: (editor) => editor.chain().focus().toggleOrderedList().run(),
    },
]

/** Keeps the text selected while clicking, so a format applies to what was selected. */
export const EmailFormatButton = forwardRef<
    HTMLButtonElement,
    { active?: boolean; label: string; attr?: string; onClick: () => void; children: JSX.Element }
>(function EmailFormatButton({ active, label, attr, onClick, children }, ref): JSX.Element {
    return (
        <LemonButton
            ref={ref}
            size="xsmall"
            noPadding
            center
            className="EmailEditor__square-button EmailEditor__square-button--compact"
            active={active}
            sideIcon={null}
            aria-label={label}
            tooltip={label}
            onMouseDown={(event) => event.preventDefault()}
            onClick={onClick}
            data-attr={attr}
        >
            {children}
        </LemonButton>
    )
})

export function EmailFormatButtons({
    editor,
    attrPrefix,
    lists,
    children,
}: {
    editor: Editor
    attrPrefix: string
    lists?: boolean
    children?: React.ReactNode
}): JSX.Element {
    return (
        <>
            {[...MARKS, ...(lists ? LISTS : [])].map(({ name, label, content, run }) => (
                <EmailFormatButton
                    key={name}
                    active={editor.isActive(name)}
                    label={label}
                    attr={`${attrPrefix}-${name}`}
                    onClick={() => run(editor)}
                >
                    {content}
                </EmailFormatButton>
            ))}
            {children}
        </>
    )
}
