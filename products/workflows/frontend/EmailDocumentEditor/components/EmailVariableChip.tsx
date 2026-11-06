import { NodeViewProps, NodeViewWrapper } from '@tiptap/react'
import clsx from 'clsx'
import { useState } from 'react'

import { IconWarning } from '@posthog/icons'
import { LemonButton, LemonInput, Popover, Tooltip } from '@posthog/lemon-ui'

import { useEmailEditorContext } from '../emailEditorContext'
import { undefinedVariableReason } from '../emailVariables'

export function EmailVariableChip({ node, selected, updateAttributes, deleteNode }: NodeViewProps): JSX.Element {
    const { variableContext } = useEmailEditorContext()
    const [open, setOpen] = useState(false)
    const { expression, fallback } = node.attrs
    const warning = undefinedVariableReason(expression, fallback, variableContext)

    const chip = (
        <button
            type="button"
            className={clsx(
                'email-canvas-variable',
                warning && 'email-canvas-variable-warning',
                selected && 'email-canvas-variable-selected'
            )}
            data-attr="email-editor-variable-chip"
            translate="no"
            onClick={() => setOpen(true)}
        >
            <span>{`{{ ${expression} }}`}</span>
            {warning ? <IconWarning className="email-canvas-variable-icon" /> : null}
        </button>
    )

    return (
        <NodeViewWrapper as="span" className="email-canvas-variable-wrapper">
            <Popover
                visible={open}
                onClickOutside={() => setOpen(false)}
                placement="bottom-start"
                overlay={
                    <div className="flex flex-col gap-2 p-2 w-72" onKeyDown={(event) => event.stopPropagation()}>
                        <label className="flex flex-col gap-1 text-xs font-semibold">
                            Variable
                            <LemonInput
                                size="small"
                                value={expression}
                                autoFocus
                                data-attr="email-editor-variable-expression"
                                onChange={(value) => updateAttributes({ expression: value })}
                            />
                        </label>
                        <label className="flex flex-col gap-1 text-xs font-semibold">
                            Fallback, if it's empty
                            <LemonInput
                                size="small"
                                value={fallback}
                                placeholder="there"
                                data-attr="email-editor-variable-fallback"
                                onChange={(value) => updateAttributes({ fallback: value })}
                            />
                        </label>
                        {warning ? <span className="text-xs text-warning-dark">{warning}</span> : null}
                        <div className="flex justify-between">
                            <LemonButton size="xsmall" status="danger" onClick={deleteNode}>
                                Remove
                            </LemonButton>
                            <LemonButton size="xsmall" type="secondary" onClick={() => setOpen(false)}>
                                Done
                            </LemonButton>
                        </div>
                    </div>
                }
            >
                <span>{warning && !open ? <Tooltip title={warning}>{chip}</Tooltip> : chip}</span>
            </Popover>
        </NodeViewWrapper>
    )
}
