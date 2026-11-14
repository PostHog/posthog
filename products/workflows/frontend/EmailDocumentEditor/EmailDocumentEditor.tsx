import './EmailDocumentEditor.scss'

import type { EditorEvents, EditorOptions } from '@tiptap/core'
import { EditorContent, useEditor } from '@tiptap/react'
import clsx from 'clsx'
import { useActions, useMountedLogic, useValues } from 'kea'
import posthog from 'posthog-js'
import { useEffect, useMemo, useRef, useState } from 'react'

import { IconRedo, IconUndo } from '@posthog/icons'
import { LemonButton, LemonSegmentedButton } from '@posthog/lemon-ui'

import { lemonToast } from 'lib/lemon-ui/LemonToast'
import { emailTemplaterLogic } from 'scenes/hog-functions/email-templater/emailTemplaterLogic'
import { teamLogic } from 'scenes/teamLogic'

import { cleanPastedHtml } from './cleanPastedHtml'
import { EmailBlockHandle } from './components/EmailBlockHandle'
import { EmailDocumentPreview } from './components/EmailDocumentPreview'
import { imageNode, insertBlockOption } from './components/emailEditorActions'
import { EmailEditorFeedback } from './components/EmailEditorFeedback'
import { EmailEditorSwitch } from './components/EmailEditorSwitch'
import { EmailImagePickerModal, PickedEmailImage } from './components/EmailImagePickerModal'
import { EmailInsertToolbar } from './components/EmailInsertToolbar'
import { EmailSelectionToolbar } from './components/EmailSelectionToolbar'
import { EmailStylePanel } from './components/EmailStylePanel'
import { EMAIL_BLOCK_OPTIONS } from './emailBlockCatalog'
import { EmailBlockKeymap, EmailLiquidHighlight } from './emailCanvasPlugins'
import { hasUnsubscribeLink, insertBlock } from './emailCommands'
import { emailDocumentFromValue, emailFontUrls, resolvePageStyle } from './emailDocument'
import { EmailDragSource } from './emailDragDrop'
import { createEmailEditorAdapter, isDocumentEdit } from './emailEditorAdapter'
import { EmailEditorContext, EmailEditorContextValue } from './emailEditorContext'
import { buildEmailExtensions } from './emailExtensions'
import { uploadEmailImage, uploadErrorText } from './emailMediaLibraryLogic'
import { EmailSuggestionItem, createEmailSuggestion } from './emailSuggestionExtension'
import { EmailVariableContext, EmailVariableOption, variableOptions as toVariableOptions } from './emailVariables'
import { renderEmailHtml, safeEmailDoc } from './renderEmailHtml'

const PLACEHOLDER = 'Write something, type / for blocks or {{ for variables'
const NARROW_WIDTH = 900

type Mode = 'edit' | 'preview'

function firstImageFile(files: FileList | null | undefined): File | null {
    return Array.from(files ?? []).find((file) => file.type.startsWith('image/')) ?? null
}

/** The new email editor, for hosts that use `emailTemplaterLogic`. */
export function EmailDocumentEditor(): JSX.Element {
    const templaterLogic = useMountedLogic(emailTemplaterLogic)
    const {
        mergeTags,
        personPropertyDefinitions,
        personPropertyDefinitionsLoading,
        logicProps,
        documentEditorInitialDoc,
        convertedEmailDocument,
    } = useValues(emailTemplaterLogic)
    const { setEmailEditorRef, onEmailEditorReady, flushPendingDesignEdit } = useActions(emailTemplaterLogic)
    const { currentProjectId } = useValues(teamLogic)
    const [mode, setMode] = useState<Mode>('edit')
    const [panelOpen, setPanelOpen] = useState(true)
    const [imagePicker, setImagePicker] = useState<((image: PickedEmailImage) => void) | null>(null)
    const [canvas, setCanvas] = useState<HTMLDivElement | null>(null)
    const [rootWidth, setRootWidth] = useState(1200)
    const rootRef = useRef<HTMLDivElement>(null)
    const suggestionsOpenRef = useRef(false)

    const [linkEditorRequest, setLinkEditorRequest] = useState(0)
    const pickImage = (onPicked: (image: PickedEmailImage) => void): void => setImagePicker(() => onPicked)
    const pickImageRef = useRef(pickImage)
    pickImageRef.current = pickImage

    const variableOptions: EmailVariableOption[] = useMemo(() => toVariableOptions(mergeTags), [mergeTags])
    const optionsRef = useRef(variableOptions)
    optionsRef.current = variableOptions

    const variableContext: EmailVariableContext = useMemo(
        () => ({
            transactional: logicProps.type === 'native_email_transactional_template',
            personProperties:
                personPropertyDefinitionsLoading && !personPropertyDefinitions.length
                    ? null
                    : personPropertyDefinitions.map((property) => property.name),
            extra: Object.keys(logicProps.variables ?? {}),
        }),
        [logicProps.type, logicProps.variables, personPropertyDefinitions, personPropertyDefinitionsLoading]
    )

    const uploadAndInsert = async (file: File): Promise<void> => {
        const toast = lemonToast.info('Uploading image...', { autoClose: false, hideButton: true })
        try {
            const media = await uploadEmailImage(String(currentProjectId), file)
            editorRef.current &&
                insertBlock(
                    editorRef.current,
                    imageNode({
                        src: media.image_location,
                        alt: '',
                        naturalWidth: media.width ?? null,
                        naturalHeight: media.height ?? null,
                        mediaId: media.id,
                    })
                )
        } catch (error) {
            lemonToast.error(uploadErrorText(error))
        } finally {
            lemonToast.dismiss(toast)
        }
    }
    const uploadRef = useRef(uploadAndInsert)
    uploadRef.current = uploadAndInsert

    const extensions = useMemo(
        () => [
            ...buildEmailExtensions(PLACEHOLDER),
            EmailLiquidHighlight,
            EmailBlockKeymap,
            EmailDragSource,
            createEmailSuggestion({
                name: 'emailBlockSuggestion',
                char: '/',
                empty: 'No blocks match. Keep typing to write text.',
                items: (query) => {
                    const lower = query.toLowerCase()
                    return EMAIL_BLOCK_OPTIONS.filter(
                        (option) => option.title.toLowerCase().includes(lower) || option.keywords.includes(lower)
                    ).map(
                        (option): EmailSuggestionItem => ({
                            key: option.key,
                            title: option.title,
                            detail: option.detail,
                            icon: option.icon,
                            run: (editor, range) => {
                                editor.chain().focus().deleteRange(range).run()
                                insertBlockOption(editor, option, (onPicked) => pickImageRef.current(onPicked))
                            },
                        })
                    )
                },
            }),
            createEmailSuggestion({
                name: 'emailVariableSuggestion',
                char: '{{',
                empty: 'Type a variable name, then }} to add it.',
                items: (query) => {
                    const lower = query.trim().toLowerCase()
                    return optionsRef.current
                        .filter(
                            (option) =>
                                option.label.toLowerCase().includes(lower) ||
                                option.expression.toLowerCase().includes(lower)
                        )
                        .slice(0, 30)
                        .map(
                            (option): EmailSuggestionItem => ({
                                key: option.expression,
                                title: option.label,
                                detail: option.expression,
                                run: (editor, range) => {
                                    editor
                                        .chain()
                                        .focus()
                                        .deleteRange(range)
                                        .insertContent([
                                            {
                                                type: 'variable',
                                                attrs: { expression: option.expression, fallback: '' },
                                            },
                                            { type: 'text', text: ' ' },
                                        ])
                                        .run()
                                },
                            })
                        )
                },
            }),
        ],
        // The extension list is fixed for the editor's life. Live values reach it through the refs above.
        // eslint-disable-next-line react-hooks/exhaustive-deps
        []
    )

    // useEditor re-applies its options when any of them is a new object, which would mean a view update per render.
    const [initialDoc] = useState(documentEditorInitialDoc)
    const editorProps = useMemo<EditorOptions['editorProps']>(
        () => ({
            attributes: { 'data-attr': 'email-editor-canvas', 'aria-label': 'Email content', spellcheck: 'true' },
            // The canvas scrolls on its own, so keep the line being typed clear of its edges.
            scrollThreshold: 48,
            scrollMargin: 48,
            handleDOMEvents: {
                // Browsers empty the label's span when dictation, autocomplete or an IME replaces all of its text,
                // and the editor then reads that back as a deletion.
                beforeinput: (view, event) => {
                    const { data, inputType } = event as InputEvent
                    const { selection } = view.state
                    if (
                        inputType === 'insertText' &&
                        data &&
                        !selection.empty &&
                        selection.$from.parent.type.name === 'emailButton' &&
                        selection.$from.sameParent(selection.$to)
                    ) {
                        event.preventDefault()
                        view.dispatch(view.state.tr.insertText(data))
                        return true
                    }
                    return false
                },
            },
            transformPastedHTML: (html) => {
                const { html: cleaned, droppedImages } = cleanPastedHtml(html)
                if (droppedImages) {
                    lemonToast.warning(
                        droppedImages === 1
                            ? "An image in what you pasted couldn't be kept. Add it with the image button."
                            : `${droppedImages} images in what you pasted couldn't be kept. Add them with the image button.`
                    )
                }
                return cleaned
            },
            handlePaste: (_view, event) => {
                const hasHtml = !!event.clipboardData?.getData('text/html')
                const file = firstImageFile(event.clipboardData?.files)
                // Word and Docs also put a picture of the copied text on the clipboard, so html wins when both exist.
                if (file && !hasHtml) {
                    void uploadRef.current(file)
                    return true
                }
                return false
            },
            handleDrop: (_view, event, _slice, moved) => {
                const file = !moved ? firstImageFile((event as DragEvent).dataTransfer?.files) : null
                if (file) {
                    event.preventDefault()
                    void uploadRef.current(file)
                    return true
                }
                return false
            },
        }),
        []
    )
    const editor = useEditor({
        extensions,
        content: safeEmailDoc(initialDoc),
        shouldRerenderOnTransaction: true,
        immediatelyRender: true,
        editorProps,
    })
    const editorRef = useRef(editor)
    editorRef.current = editor
    // ProseMirror selects a leading image on load, which shouldn't look selected before anyone has touched the email.
    const [touched, setTouched] = useState(false)
    useEffect(() => {
        const onFocus = (): void => setTouched(true)
        editor.on('focus', onFocus)
        return () => {
            editor.off('focus', onFocus)
        }
    }, [editor])

    useEffect(() => {
        const onBlur = (): void => flushPendingDesignEdit()
        editor.on('blur', onBlur)
        const adapter = createEmailEditorAdapter(editor)
        setEmailEditorRef({ editor: adapter } as any)
        onEmailEditorReady()
        // pinned: analytics event name and property, renaming breaks dashboards
        posthog.capture('email editor opened', {
            email_type: logicProps.type,
            source: convertedEmailDocument
                ? 'converted'
                : emailDocumentFromValue(logicProps.value).document
                  ? 'document'
                  : 'new',
        })
        const onFirstEdit = (event: EditorEvents['update']): void => {
            if (!isDocumentEdit(event)) {
                return
            }
            if (convertedEmailDocument) {
                // pinned: analytics event name and property, renaming breaks dashboards
                posthog.capture('email editor converted email edited', { email_type: logicProps.type })
            }
            editor.off('update', onFirstEdit)
        }
        editor.on('update', onFirstEdit)
        return () => {
            editor.off('blur', onBlur)
            editor.off('update', onFirstEdit)
            adapter.destroy()
            // When the old editor takes over, its ref is attached before this cleanup runs.
            if (templaterLogic.isMounted() && templaterLogic.values.emailEditorRef?.editor === adapter) {
                setEmailEditorRef(null)
            }
        }
        // The adapter belongs to this editor instance, which lives as long as the component.
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [editor])

    useEffect(() => {
        const element = rootRef.current
        if (!element) {
            return
        }
        const observer = new ResizeObserver(([entry]) => setRootWidth(entry.contentRect.width))
        observer.observe(element)
        return () => observer.disconnect()
    }, [])

    const narrow = rootWidth < NARROW_WIDTH
    useEffect(() => {
        setPanelOpen(!narrow)
    }, [narrow])

    const context: EmailEditorContextValue = useMemo(
        () => ({
            variableContext,
            variableOptions,
            pickImage,
            openLinkEditor: () => setLinkEditorRequest((request) => request + 1),
        }),
        // pickImage only sets state, so it stays valid between renders.
        // eslint-disable-next-line react-hooks/exhaustive-deps
        [variableContext, variableOptions]
    )

    const doc = editor.getJSON()
    const page = resolvePageStyle(doc.attrs?.page)
    const html = mode === 'preview' ? renderEmailHtml(doc) : ''

    return (
        <EmailEditorContext.Provider value={context}>
            <div
                ref={rootRef}
                className="flex flex-col flex-1 min-h-0 min-w-0"
                data-attr="email-document-editor"
                onSubmit={(event) => {
                    // The hosts wrap this in their own form, and nothing in here should submit it.
                    event.preventDefault()
                    event.stopPropagation()
                }}
                // Read before the editor handles the key, because closing the menu removes it from the page.
                onKeyDownCapture={(event) => {
                    suggestionsOpenRef.current =
                        event.key === 'Escape' && !!document.querySelector('[data-attr=email-editor-suggestions]')
                }}
                onKeyDown={(event) => {
                    const target = event.target as HTMLElement
                    if (event.key === 'Enter' && target.tagName === 'INPUT') {
                        event.preventDefault()
                    }
                    // The fullscreen editor closes on Escape at the window. An open menu or dialog takes it first.
                    if (
                        event.key === 'Escape' &&
                        (suggestionsOpenRef.current || target.closest?.('.ReactModal__Overlay, .Popover'))
                    ) {
                        event.stopPropagation()
                    }
                }}
            >
                <div className="flex items-center gap-1 flex-wrap px-2 py-1 border-b shrink-0">
                    <LemonSegmentedButton
                        size="xsmall"
                        value={mode}
                        onChange={setMode}
                        options={[
                            { value: 'edit', label: 'Edit', 'data-attr': 'email-editor-mode-edit' },
                            { value: 'preview', label: 'Preview', 'data-attr': 'email-editor-mode-preview' },
                        ]}
                    />
                    {mode === 'edit' ? (
                        <>
                            <LemonButton
                                size="xsmall"
                                icon={<IconUndo />}
                                aria-label="Undo"
                                tooltip="Undo"
                                data-attr="email-editor-undo"
                                disabledReason={editor.can().undo() ? undefined : 'Nothing to undo'}
                                onClick={() => editor.chain().focus().undo().run()}
                            />
                            <LemonButton
                                size="xsmall"
                                icon={<IconRedo />}
                                aria-label="Redo"
                                tooltip="Redo"
                                data-attr="email-editor-redo"
                                disabledReason={editor.can().redo() ? undefined : 'Nothing to redo'}
                                onClick={() => editor.chain().focus().redo().run()}
                            />
                        </>
                    ) : null}
                    <div className="flex-1" />
                    <EmailEditorSwitch.UseOldButton />
                    {mode === 'edit' ? (
                        <LemonButton
                            size="xsmall"
                            active={panelOpen}
                            data-attr="email-editor-toggle-panel"
                            onClick={() => setPanelOpen(!panelOpen)}
                        >
                            Style
                        </LemonButton>
                    ) : null}
                </div>
                <EmailEditorSwitch.ConvertedNotice />
                <EmailEditorFeedback />
                {mode === 'preview' ? (
                    <EmailDocumentPreview html={html} unsubscribeMissing={!!html && !hasUnsubscribeLink(html)} />
                ) : (
                    <div className="flex flex-1 min-h-0 relative">
                        <div
                            ref={setCanvas}
                            className="EmailDocumentEditor__scroll relative flex-1 min-w-0 overflow-auto"
                            style={{ backgroundColor: page.backgroundColor }}
                            data-attr="email-editor-scroll"
                        >
                            <div className="EmailDocumentEditor__toolbar sticky top-2 z-10 h-0 pl-2">
                                <div className="inline-block">
                                    <EmailInsertToolbar editor={editor} />
                                </div>
                            </div>
                            <div
                                className="EmailDocumentEditor__body mx-auto"
                                style={{
                                    maxWidth: page.bodyWidth,
                                    padding: page.padding || undefined,
                                    marginLeft: page.align === 'left' ? 0 : undefined,
                                    marginRight: page.align === 'right' ? 0 : undefined,
                                }}
                            >
                                <div
                                    className={clsx(
                                        'EmailDocumentCanvas',
                                        !touched && 'EmailDocumentCanvas--untouched'
                                    )}
                                    style={
                                        {
                                            backgroundColor: page.bodyBackgroundColor,
                                            color: page.textColor,
                                            fontFamily: page.fontFamily,
                                            fontSize: page.fontSize,
                                            // Unitless, because a percentage inherits as a fixed size and larger text would overlap.
                                            lineHeight: page.lineHeight / 100,
                                            padding: `${page.bodyPadding.top}px ${page.bodyPadding.right}px ${page.bodyPadding.bottom}px ${page.bodyPadding.left}px`,
                                            borderRadius: page.bodyBorderRadius || undefined,
                                            border: page.bodyBorderWidth
                                                ? `${page.bodyBorderWidth}px solid ${page.bodyBorderColor}`
                                                : undefined,
                                            '--email-link': page.linkColor,
                                            '--email-button-background': page.buttonBackgroundColor,
                                            '--email-button-text': page.buttonTextColor,
                                            '--email-button-radius': `${page.buttonBorderRadius}px`,
                                        } as React.CSSProperties
                                    }
                                >
                                    <style>{`.EmailDocumentCanvas .ProseMirror h1{font-size:${page.h1Size}px}.EmailDocumentCanvas .ProseMirror h2{font-size:${page.h2Size}px}.EmailDocumentCanvas .ProseMirror h3{font-size:${page.h3Size}px}`}</style>
                                    {/* Only Google Fonts loads in the app page. The email itself can use any stylesheet. */}
                                    {emailFontUrls(doc)
                                        .filter((url) => url.startsWith('https://fonts.googleapis.com/'))
                                        .map((url) => (
                                            <link key={url} rel="stylesheet" href={url} />
                                        ))}
                                    <EditorContent editor={editor} />
                                </div>
                            </div>
                            <EmailBlockHandle editor={editor} container={canvas} />
                            <EmailSelectionToolbar editor={editor} container={canvas} openRequest={linkEditorRequest} />
                        </div>
                        {panelOpen ? (
                            <div
                                className={
                                    narrow
                                        ? 'absolute right-0 top-0 bottom-0 z-20 w-72 border-l bg-surface-primary shadow'
                                        : 'w-72 shrink-0 border-l bg-surface-primary'
                                }
                            >
                                <EmailStylePanel
                                    editor={editor}
                                    onClose={narrow ? () => setPanelOpen(false) : undefined}
                                />
                            </div>
                        ) : null}
                    </div>
                )}
                <EmailImagePickerModal
                    isOpen={!!imagePicker}
                    onAfterClose={() => editor.commands.focus()}
                    onClose={() => setImagePicker(null)}
                    onPick={(image) => {
                        imagePicker?.(image)
                        setImagePicker(null)
                    }}
                />
            </div>
        </EmailEditorContext.Provider>
    )
}
