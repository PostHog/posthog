import type { ReactElement } from 'react'

import type { RowAnchor } from '@/features/inbox/contextMenuPlacement'
import { MenuCard, MenuItem } from '@/features/views/list/ViewsMenu'
import { ChevronRightIcon } from '@/ui/icons/ChevronRightIcon'
import { PinIcon } from '@/ui/icons/PinIcon'
import { useColors } from '@/ui/theme'

interface NavPinMenuProps {
    visible: boolean
    anchor: RowAnchor
    label: string
    pinned: boolean
    onClose: () => void
    onTogglePin: () => void
    onOpen: () => void
}

export function NavPinMenu({
    visible,
    anchor,
    label,
    pinned,
    onClose,
    onTogglePin,
    onOpen,
}: NavPinMenuProps): ReactElement {
    const colors = useColors()
    return (
        <MenuCard
            visible={visible}
            anchor={anchor}
            onClose={onClose}
            accessibilityLabel={`${label} actions`}
            testID="nav-pin-menu"
        >
            <MenuItem
                label={pinned ? 'Unpin from navigation' : 'Pin to navigation'}
                onPress={onTogglePin}
                trailing={<PinIcon size={18} filled={pinned} color={colors.ink} />}
                testID={pinned ? 'nav-pin-menu-unpin' : 'nav-pin-menu-pin'}
            />
            <MenuItem
                label="Open"
                onPress={onOpen}
                trailing={<ChevronRightIcon size={13} color={colors.ink} />}
                testID="nav-pin-menu-open"
            />
        </MenuCard>
    )
}
