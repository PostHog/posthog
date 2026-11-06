import type { Editor } from '@tiptap/core'
import { useEffect, useState } from 'react'

import { IconArrowLeft } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { EmailBlockFields } from './EmailBlockFields'
import { EmailPageStyleFields } from './EmailPageStyleFields'

export function EmailStylePanel({ editor, onClose }: { editor: Editor; onClose?: () => void }): JSX.Element {
    const [showPage, setShowPage] = useState(true)

    useEffect(() => {
        const onSelection = (): void => {
            // Loading the saved email moves the selection too. Only a person's own move opens the block's settings.
            if (editor.isFocused) {
                setShowPage(false)
            }
        }
        const onFocus = (): void => setShowPage(false)
        editor.on('selectionUpdate', onSelection)
        editor.on('focus', onFocus)
        return () => {
            editor.off('selectionUpdate', onSelection)
            editor.off('focus', onFocus)
        }
    }, [editor])

    return (
        <div className="flex flex-col gap-2 p-3 overflow-y-auto h-full" data-attr="email-editor-style-panel">
            <div className="flex items-center gap-1">
                {showPage ? (
                    <h3 className="text-sm font-semibold m-0 flex-1">Page style</h3>
                ) : (
                    <LemonButton
                        size="xsmall"
                        icon={<IconArrowLeft />}
                        className="flex-1"
                        onClick={() => setShowPage(true)}
                        data-attr="email-editor-panel-page"
                    >
                        Page style
                    </LemonButton>
                )}
                {onClose ? (
                    <LemonButton size="xsmall" onClick={onClose} data-attr="email-editor-panel-close">
                        Hide
                    </LemonButton>
                ) : null}
            </div>
            {showPage ? <EmailPageStyleFields editor={editor} /> : <EmailBlockFields editor={editor} />}
        </div>
    )
}
