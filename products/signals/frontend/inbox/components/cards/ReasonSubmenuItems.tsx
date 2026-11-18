import { Fragment } from 'react'

import { IconPencil } from '@posthog/icons'

import { ButtonGroupPrimitive, ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { ContextMenuGroup, ContextMenuItem, ContextMenuSeparator } from 'lib/ui/ContextMenu/ContextMenu'

export function ReasonSubmenuItems<T extends string>({
    options,
    noteTooltip,
    dataAttrPrefix,
    onPick,
    onPickWithNote,
}: {
    options: readonly { readonly value: T; readonly label: string }[]
    noteTooltip: string
    dataAttrPrefix: string
    onPick: (reason: T) => void
    onPickWithNote: (reason: T) => void
}): JSX.Element {
    return (
        <ContextMenuGroup>
            {options.map((option) =>
                option.value === 'other' ? (
                    <Fragment key={option.value}>
                        <ContextMenuSeparator />
                        <ButtonGroupPrimitive fullWidth>
                            <ContextMenuItem asChild>
                                <ButtonPrimitive
                                    menuItem
                                    hasSideActionRight
                                    onClick={() => onPick(option.value)}
                                    data-attr={`${dataAttrPrefix}-reason`}
                                >
                                    Other
                                </ButtonPrimitive>
                            </ContextMenuItem>
                            <ContextMenuItem asChild>
                                <ButtonPrimitive
                                    iconOnly
                                    isSideActionRight
                                    tooltip={noteTooltip}
                                    aria-label={noteTooltip}
                                    onClick={() => onPickWithNote(option.value)}
                                    data-attr={`${dataAttrPrefix}-note`}
                                >
                                    <IconPencil />
                                </ButtonPrimitive>
                            </ContextMenuItem>
                        </ButtonGroupPrimitive>
                    </Fragment>
                ) : (
                    <ContextMenuItem asChild key={option.value}>
                        <ButtonPrimitive
                            menuItem
                            onClick={() => onPick(option.value)}
                            data-attr={`${dataAttrPrefix}-reason`}
                        >
                            {option.label}
                        </ButtonPrimitive>
                    </ContextMenuItem>
                )
            )}
        </ContextMenuGroup>
    )
}
