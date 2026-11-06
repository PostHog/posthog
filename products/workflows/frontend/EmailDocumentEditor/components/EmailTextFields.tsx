import type { Editor } from '@tiptap/core'

import { LemonButton, LemonSelect } from '@posthog/lemon-ui'

import { EmailBlockStyle, resolvePageStyle } from '../emailDocument'
import { useEmailEditorContext } from '../emailEditorContext'
import { EmailAlignField } from './fields/EmailAlignField'
import { EmailColorField } from './fields/EmailColorField'
import { EmailFieldRow } from './fields/EmailFieldRow'
import { EmailNumberField } from './fields/EmailNumberField'

export function EmailTextFields({
    editor,
    nodeType,
    level,
    style,
    set,
}: {
    editor: Editor
    nodeType: string
    level?: number
    style: EmailBlockStyle
    set: (patch: Partial<EmailBlockStyle>) => void
}): JSX.Element {
    const { openLinkEditor } = useEmailEditorContext()
    const showLink = !editor.state.selection.empty || editor.isActive('link')
    const page = resolvePageStyle(editor.state.doc.attrs.page)
    const size =
        nodeType === 'heading' ? (level === 1 ? page.h1Size : level === 2 ? page.h2Size : page.h3Size) : page.fontSize
    const isTextBlock = nodeType === 'paragraph' || nodeType === 'heading'
    const toggle = (name: string, label: string, content: JSX.Element, run: () => void): JSX.Element => (
        <LemonButton
            size="xsmall"
            active={editor.isActive(name)}
            aria-label={label}
            tooltip={label}
            onClick={run}
            data-attr={`email-editor-panel-${name}`}
        >
            {content}
        </LemonButton>
    )
    return (
        <>
            {isTextBlock ? (
                <EmailFieldRow label="Style">
                    <LemonSelect
                        size="small"
                        fullWidth
                        value={nodeType === 'heading' ? `h${level}` : 'p'}
                        options={[
                            { value: 'p', label: 'Text' },
                            { value: 'h1', label: 'Heading 1' },
                            { value: 'h2', label: 'Heading 2' },
                            { value: 'h3', label: 'Heading 3' },
                        ]}
                        data-attr="email-editor-text-style"
                        onChange={(value) => {
                            const chain = editor.chain().focus()
                            if (value === 'p') {
                                chain.setParagraph().run()
                            } else {
                                chain.setHeading({ level: Number(value[1]) as 1 | 2 | 3 }).run()
                            }
                        }}
                    />
                </EmailFieldRow>
            ) : null}
            <EmailColorField
                label="Color"
                value={style.color}
                placeholder={page.textColor}
                onChange={(color) => set({ color })}
                attr="email-editor-text-color"
            />
            <EmailNumberField
                label="Font size"
                value={style.fontSize}
                placeholder={size}
                min={8}
                max={96}
                onChange={(fontSize) => set({ fontSize })}
                attr="email-editor-font-size"
            />
            <EmailNumberField
                label="Line height"
                suffix="%"
                value={style.lineHeight}
                placeholder={nodeType === 'heading' ? 125 : page.lineHeight}
                min={80}
                max={300}
                onChange={(lineHeight) => set({ lineHeight })}
            />
            <EmailNumberField
                label="Letter spacing"
                value={style.letterSpacing}
                placeholder={0}
                onChange={(letterSpacing) => set({ letterSpacing })}
            />
            <div className="flex flex-wrap gap-0.5 py-1">
                {toggle('bold', 'Bold', <span className="font-bold px-1 text-xs">B</span>, () =>
                    editor.chain().focus().toggleBold().run()
                )}
                {toggle('italic', 'Italic', <span className="italic px-1 text-xs">I</span>, () =>
                    editor.chain().focus().toggleItalic().run()
                )}
                {toggle('underline', 'Underline', <span className="underline px-1 text-xs">U</span>, () =>
                    editor.chain().focus().toggleUnderline().run()
                )}
                {toggle('strike', 'Strikethrough', <span className="line-through px-1 text-xs">S</span>, () =>
                    editor.chain().focus().toggleStrike().run()
                )}
                {toggle('code', 'Code', <span className="font-mono px-0.5 text-xs">{'<>'}</span>, () =>
                    editor.chain().focus().toggleCode().run()
                )}
                <LemonButton
                    size="xsmall"
                    active={!!style.uppercase}
                    aria-label="Uppercase"
                    tooltip="Uppercase"
                    onClick={() => set({ uppercase: style.uppercase ? undefined : true })}
                >
                    <span className="px-0.5 text-xs">AB</span>
                </LemonButton>
                {toggle('bulletList', 'Bullet list', <span className="px-1 text-xs">•</span>, () =>
                    editor.chain().focus().toggleBulletList().run()
                )}
                {toggle('orderedList', 'Numbered list', <span className="px-1 text-xs">1.</span>, () =>
                    editor.chain().focus().toggleOrderedList().run()
                )}
            </div>
            <EmailAlignField value={style.textAlign} onChange={(textAlign) => set({ textAlign })} />
            {showLink ? (
                <LemonButton
                    size="xsmall"
                    type="secondary"
                    fullWidth
                    center
                    data-attr="email-editor-panel-link"
                    onClick={() => openLinkEditor()}
                >
                    {editor.isActive('link') ? 'Edit link' : 'Add link'}
                </LemonButton>
            ) : null}
        </>
    )
}
