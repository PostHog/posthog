import { useActions, useValues } from 'kea'
import type { ReactNode } from 'react'

import { IconArrowLeft } from '@posthog/icons'
import { Tooltip as LemonTooltip } from '@posthog/lemon-ui'

import { Button, Heading } from 'lib/ui/quill'

import { IssueFilterPreview, issueFilterPreviewLogic } from './issueFilterPreviewLogic'

interface IssueFilterPreviewHeaderProps {
    preview: IssueFilterPreview
    title: string
    children?: ReactNode
}

export function IssueFilterPreviewHeader({ preview, title, children }: IssueFilterPreviewHeaderProps): JSX.Element {
    const { activePreview, canUndoActivePreview } = useValues(issueFilterPreviewLogic)
    const { undoActivePreview } = useActions(issueFilterPreviewLogic)
    const canUndo = activePreview === preview && canUndoActivePreview

    return (
        <div className="sticky top-0 z-10 flex h-10 shrink-0 items-center justify-between gap-2 border-b border-primary bg-[var(--background)] px-3">
            <div className="flex shrink-0 items-center gap-1.5">
                {canUndo && (
                    <div className="flex size-6 shrink-0 items-center justify-center">
                        <LemonTooltip title="Undo filter">
                            <Button
                                variant="default"
                                size="icon-sm"
                                aria-label="Undo filter"
                                data-attr="error-tracking-undo-preview-filter"
                                onClick={undoActivePreview}
                            >
                                <IconArrowLeft />
                            </Button>
                        </LemonTooltip>
                    </div>
                )}
                <Heading size="sm">{title}</Heading>
            </div>
            {children ? (
                <div className="hide-scrollbar h-full min-w-0 flex-1 overflow-x-auto overflow-y-hidden">
                    <div className="flex h-full w-max min-w-full items-center justify-end">{children}</div>
                </div>
            ) : null}
        </div>
    )
}
