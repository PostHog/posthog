import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { IconCopy, IconDrag, IconTrash } from '@posthog/icons'

import { LemonMenu } from 'lib/lemon-ui/LemonMenu'

import type { HogFlowAction } from '../../types'
import { tileCanvasLogic } from './tileCanvasLogic'

const MENU_CLASS = 'TileStepMenu'

const tileOf = (actionId: string): HTMLElement | undefined =>
    [...document.querySelectorAll<HTMLElement>('.react-flow__node')].find((node) => node.dataset.id === actionId)

/**
 * A menu opened from the keyboard takes focus, so its items can be reached, and hands it back to the tile when it
 * closes. Escape closes it, and so does moving focus out of it.
 */
function useKeyboardMenuFocus(open: boolean, actionId: string, close: () => void): void {
    useEffect(() => {
        if (!open) {
            return
        }
        const tile = tileOf(actionId)
        const menu = (): HTMLElement | null => document.querySelector<HTMLElement>(`.${MENU_CLASS}`)
        const frame = requestAnimationFrame(() =>
            menu()?.querySelector<HTMLElement>('button:not(:disabled):not([aria-disabled="true"])')?.focus()
        )
        const onKeyDown = (event: KeyboardEvent): void => {
            if (event.key === 'Escape' && menu()?.contains(event.target as Node)) {
                event.preventDefault()
                close()
            }
        }
        const onFocusIn = (event: FocusEvent): void => {
            const target = event.target as Node
            if (!menu()?.contains(target) && target !== tile) {
                close()
            }
        }
        document.addEventListener('keydown', onKeyDown, true)
        document.addEventListener('focusin', onFocusIn)
        return () => {
            cancelAnimationFrame(frame)
            document.removeEventListener('keydown', onKeyDown, true)
            document.removeEventListener('focusin', onFocusIn)
            const focusIsLost = !document.activeElement || document.activeElement === document.body
            if (focusIsLost || menu()?.contains(document.activeElement)) {
                tile?.focus()
            }
        }
    }, [open, actionId, close])
}

export function TileStepMenu({ action, children }: { action: HogFlowAction; children: JSX.Element }): JSX.Element {
    const {
        stepMenuActionId,
        stepMenuFromKeyboard,
        selectedNode,
        selectedNodeCanBeDeleted,
        selectedNodeCanBeCopiedOrMoved,
        stepHasMenu,
    } = useValues(tileCanvasLogic)
    const { closeStepMenu, chooseStepMenuItem } = useActions(tileCanvasLogic)
    const node = selectedNode?.id === action.id ? selectedNode : null
    const visible = stepMenuActionId === action.id && !!node
    useKeyboardMenuFocus(visible && stepMenuFromKeyboard, action.id, closeStepMenu)

    if (!stepHasMenu(action)) {
        return children
    }

    return (
        <LemonMenu
            visible={visible}
            className={MENU_CLASS}
            onVisibilityChange={(visible) => !visible && closeStepMenu()}
            placement="right-start"
            items={
                node
                    ? [
                          selectedNodeCanBeCopiedOrMoved
                              ? {
                                    label: 'Copy',
                                    icon: <IconCopy />,
                                    'data-attr': 'workflow-tile-step-copy',
                                    onClick: () => chooseStepMenuItem('copy'),
                                }
                              : null,
                          selectedNodeCanBeCopiedOrMoved
                              ? {
                                    label: 'Move',
                                    icon: <IconDrag />,
                                    'data-attr': 'workflow-tile-step-move',
                                    onClick: () => chooseStepMenuItem('move'),
                                }
                              : null,
                          {
                              label: 'Delete',
                              status: 'danger',
                              icon: <IconTrash />,
                              'data-attr': 'workflow-tile-step-delete',
                              onClick: () => chooseStepMenuItem('delete'),
                              disabledReason: selectedNodeCanBeDeleted ? undefined : 'Clean up branching steps first',
                          },
                      ]
                    : []
            }
        >
            {children}
        </LemonMenu>
    )
}
