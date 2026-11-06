import type { Editor } from '@tiptap/core'

import { LemonButton, LemonSelect } from '@posthog/lemon-ui'

import { EMAIL_FONTS, EmailBlockStyle, fontOptions, resolvePageStyle } from '../emailDocument'
import { useEmailEditorContext } from '../emailEditorContext'
import { EmailFormatButton, EmailFormatButtons } from './EmailFormatButtons'
import { EmailAlignField } from './fields/EmailAlignField'
import { EmailColorField } from './fields/EmailColorField'
import { EmailFieldRow } from './fields/EmailFieldRow'
import { EmailNumberField } from './fields/EmailNumberField'
import { EmailWeightField } from './fields/EmailWeightField'

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
            <EmailFieldRow label="Font">
                <LemonSelect
                    size="small"
                    fullWidth
                    value={style.fontFamily ?? null}
                    options={[{ value: null, label: 'Same as page' }, ...fontOptions(style.fontFamily)]}
                    data-attr="email-editor-text-font"
                    onChange={(fontFamily) =>
                        set({
                            fontFamily: fontFamily ?? undefined,
                            fontUrl: EMAIL_FONTS.find((font) => font.value === fontFamily)?.url,
                        })
                    }
                />
            </EmailFieldRow>
            <EmailColorField
                label="Color"
                value={style.color}
                placeholder={page.textColor}
                onChange={(color) => set({ color })}
                attr="email-editor-text-color"
            />
            <EmailWeightField
                value={style.fontWeight}
                fallback={nodeType === 'heading' ? 700 : 400}
                onChange={(fontWeight) => set({ fontWeight })}
                attr="email-editor-text-weight"
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
                attr="email-editor-line-height"
            />
            <EmailNumberField
                label="Letter spacing"
                value={style.letterSpacing}
                placeholder={0}
                onChange={(letterSpacing) => set({ letterSpacing })}
                attr="email-editor-letter-spacing"
            />
            <div className="flex flex-wrap gap-0.5 py-1">
                <EmailFormatButtons editor={editor} attrPrefix="email-editor-panel" lists>
                    <EmailFormatButton
                        active={!!style.uppercase}
                        label="Uppercase"
                        attr="email-editor-panel-uppercase"
                        onClick={() => set({ uppercase: style.uppercase ? undefined : true })}
                    >
                        <span className="text-xxs font-semibold leading-none">AB</span>
                    </EmailFormatButton>
                </EmailFormatButtons>
            </div>
            {!editor.state.selection.empty ? (
                <>
                    <EmailColorField
                        label="Selected color"
                        value={editor.getAttributes('textStyle').color ?? undefined}
                        placeholder={style.color ?? page.textColor}
                        onChange={(color) =>
                            color ? editor.chain().setColor(color).run() : editor.chain().unsetColor().run()
                        }
                        attr="email-editor-selection-color"
                    />
                    <EmailNumberField
                        label="Selected size"
                        value={editor.getAttributes('textStyle').fontSize ?? undefined}
                        placeholder={style.fontSize ?? size}
                        min={8}
                        max={96}
                        onChange={(fontSize) =>
                            editor
                                .chain()
                                .setMark('textStyle', { fontSize: fontSize ?? null })
                                .run()
                        }
                        attr="email-editor-selection-size"
                    />
                </>
            ) : null}
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
