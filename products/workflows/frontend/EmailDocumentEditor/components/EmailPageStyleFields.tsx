import type { Editor } from '@tiptap/core'

import { LemonCollapse, LemonDivider, LemonInput, LemonSelect } from '@posthog/lemon-ui'

import { CodeEditor } from 'lib/monaco/CodeEditor'

import { setPageStyle } from '../emailCommands'
import { DEFAULT_EMAIL_PAGE_STYLE, EMAIL_FONTS, EmailPageStyle, fontOptions, resolvePageStyle } from '../emailDocument'
import { EmailAlignField } from './fields/EmailAlignField'
import { EmailColorField } from './fields/EmailColorField'
import { EmailFieldRow } from './fields/EmailFieldRow'
import { EmailNumberField } from './fields/EmailNumberField'
import { EmailSectionTitle } from './fields/EmailSectionTitle'
import { EmailSidesField } from './fields/EmailSidesField'

export function EmailPageStyleFields({ editor }: { editor: Editor }): JSX.Element {
    const page = resolvePageStyle(editor.state.doc.attrs.page)
    const set = (patch: Partial<EmailPageStyle>): void => setPageStyle(editor, patch)
    const required = <K extends keyof EmailPageStyle>(key: K) =>
        ((value: EmailPageStyle[K] | undefined) => set({ [key]: value ?? DEFAULT_EMAIL_PAGE_STYLE[key] })) as (
            value: any
        ) => void

    return (
        <div className="flex flex-col gap-1">
            <EmailColorField
                label="Background"
                value={page.backgroundColor}
                onChange={required('backgroundColor')}
                attr="email-editor-page-background"
            />
            <EmailNumberField
                label="Padding"
                value={page.padding}
                onChange={required('padding')}
                attr="email-editor-page-padding"
            />
            <EmailFieldRow label="Preview text">
                <LemonInput
                    size="small"
                    fullWidth
                    placeholder="Shown after the subject"
                    value={page.previewText}
                    onChange={(previewText) => set({ previewText })}
                    data-attr="email-editor-preview-text"
                />
            </EmailFieldRow>
            <LemonDivider className="my-1" />
            <EmailSectionTitle>Body</EmailSectionTitle>
            <EmailAlignField value={page.align} onChange={(align) => set({ align })} />
            <EmailColorField
                label="Text"
                value={page.textColor}
                onChange={required('textColor')}
                attr="email-editor-body-text"
            />
            <EmailColorField
                label="Background"
                value={page.bodyBackgroundColor}
                onChange={required('bodyBackgroundColor')}
                attr="email-editor-body-background"
            />
            <EmailNumberField
                label="Width"
                value={page.bodyWidth}
                min={200}
                max={1200}
                onChange={required('bodyWidth')}
                attr="email-editor-body-width"
            />
            <EmailSidesField
                label="Padding"
                value={page.bodyPadding}
                placeholder={DEFAULT_EMAIL_PAGE_STYLE.bodyPadding}
                onChange={required('bodyPadding')}
                attr="email-editor-body-padding"
            />
            <EmailNumberField
                label="Corner radius"
                value={page.bodyBorderRadius}
                onChange={required('bodyBorderRadius')}
                attr="email-editor-body-radius"
            />
            <EmailNumberField
                label="Border"
                value={page.bodyBorderWidth}
                onChange={required('bodyBorderWidth')}
                attr="email-editor-body-border"
            />
            {page.bodyBorderWidth ? (
                <EmailColorField
                    label="Border color"
                    value={page.bodyBorderColor}
                    onChange={required('bodyBorderColor')}
                />
            ) : null}
            <LemonDivider className="my-1" />
            <LemonCollapse
                embedded
                size="small"
                panels={[
                    {
                        key: 'theme',
                        header: 'Theme',
                        dataAttr: 'email-editor-theme-toggle',
                        content: (
                            <div className="flex flex-col gap-1">
                                <EmailFieldRow label="Font">
                                    <LemonSelect
                                        size="small"
                                        fullWidth
                                        value={page.fontFamily}
                                        options={fontOptions(page.fontFamily)}
                                        onChange={(fontFamily) =>
                                            set({
                                                fontFamily,
                                                fontUrl:
                                                    EMAIL_FONTS.find((font) => font.value === fontFamily)?.url ?? '',
                                            })
                                        }
                                        data-attr="email-editor-theme-font"
                                    />
                                </EmailFieldRow>
                                <EmailNumberField
                                    label="Font size"
                                    value={page.fontSize}
                                    min={8}
                                    max={40}
                                    onChange={required('fontSize')}
                                    attr="email-editor-theme-font-size"
                                />
                                <EmailNumberField
                                    label="Line height"
                                    suffix="%"
                                    value={page.lineHeight}
                                    min={80}
                                    max={300}
                                    onChange={required('lineHeight')}
                                />
                                <EmailColorField
                                    label="Links"
                                    value={page.linkColor}
                                    onChange={required('linkColor')}
                                    attr="email-editor-theme-link"
                                />
                                <EmailNumberField label="Heading 1" value={page.h1Size} onChange={required('h1Size')} />
                                <EmailNumberField label="Heading 2" value={page.h2Size} onChange={required('h2Size')} />
                                <EmailNumberField label="Heading 3" value={page.h3Size} onChange={required('h3Size')} />
                                <EmailColorField
                                    label="Button"
                                    value={page.buttonBackgroundColor}
                                    onChange={required('buttonBackgroundColor')}
                                    attr="email-editor-theme-button"
                                />
                                <EmailColorField
                                    label="Button text"
                                    value={page.buttonTextColor}
                                    onChange={required('buttonTextColor')}
                                />
                                <EmailNumberField
                                    label="Button radius"
                                    value={page.buttonBorderRadius}
                                    onChange={required('buttonBorderRadius')}
                                />
                            </div>
                        ),
                    },
                    {
                        key: 'css',
                        header: 'Global CSS',
                        dataAttr: 'email-editor-css-toggle',
                        content: (
                            <div className="flex flex-col gap-1">
                                <span className="text-xs text-secondary">
                                    Added to the email's head. Some email apps, including Outlook, ignore parts of it.
                                </span>
                                <CodeEditor
                                    language="css"
                                    height={160}
                                    value={page.globalCss}
                                    onChange={(value) => set({ globalCss: value ?? '' })}
                                    options={{ minimap: { enabled: false }, lineNumbers: 'off', wordWrap: 'on' }}
                                />
                            </div>
                        ),
                    },
                ]}
            />
        </div>
    )
}
