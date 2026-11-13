import { Placeholder } from '@tiptap/extensions'
import { EditorContent } from '@tiptap/react'
import { useMountedLogic } from 'kea'
import { useMemo, useRef, useState } from 'react'

import { useRichContentEditor } from 'lib/components/RichContentEditor'
import { CommandEnterExtension } from 'lib/components/RichContentEditor/CommandEnterExtension'
import { DEFAULT_EXTENSIONS, serializationOptions } from 'lib/components/RichContentEditor/LemonRichContentEditor'
import { mentionRolesLogic } from 'lib/components/RichContentEditor/mentionRolesLogic'
import { MentionsExtension } from 'lib/components/RichContentEditor/MentionsExtension'
import { TTEditor } from 'lib/components/RichContentEditor/types'
import { cn } from 'lib/utils/css-classes'

/**
 * A note box where `@` mentions people and roles. It reports the note as plain text with
 * `@member:<id>` and `@role:<uuid>` tokens, which is the shape the notes API stores and the notes
 * list renders as chips.
 */
export function ReportNoteEditor({
    onChange,
    onPressCmdEnter,
    placeholder,
    maxLength,
}: {
    onChange: (text: string) => void
    onPressCmdEnter: () => void
    placeholder: string
    maxLength: number
}): JSX.Element {
    // Keeps roles loaded while the box is open, so each `@` does not refetch them.
    useMountedLogic(mentionRolesLogic)
    const editorRef = useRef<TTEditor | null>(null)
    // The editor reads its extensions and callbacks once, so they go through refs to see the latest props.
    const onChangeRef = useRef(onChange)
    onChangeRef.current = onChange
    const onPressCmdEnterRef = useRef(onPressCmdEnter)
    onPressCmdEnterRef.current = onPressCmdEnter
    const [length, setLength] = useState(0)
    const extensions = useMemo(
        () => [
            ...DEFAULT_EXTENSIONS.filter((extension) => extension !== MentionsExtension),
            MentionsExtension.configure({ includeRoles: true }),
            Placeholder.configure({ placeholder }),
            CommandEnterExtension.configure({ onPressCmdEnter: () => onPressCmdEnterRef.current() }),
        ],
        [placeholder]
    )
    const editor = useRichContentEditor({
        extensions,
        autoFocus: true,
        onCreate: (created) => {
            editorRef.current = created
        },
        onUpdate: () => {
            const text = editorRef.current?.getText(serializationOptions) ?? ''
            setLength(text.length)
            onChangeRef.current(text)
        },
    })

    return (
        <div className="LemonRichContentEditor flex flex-col rounded border input-like">
            <EditorContent editor={editor} className="RichContentEditor p-2 min-h-16" />
            {/* Mentions count as their stored tokens, so the count only shows near the limit where it matters. */}
            {length > maxLength * 0.9 && (
                <span
                    className={cn('self-end px-2 pb-1 text-xs', length > maxLength ? 'text-danger' : 'text-tertiary')}
                >
                    {length} / {maxLength}
                </span>
            )}
        </div>
    )
}
