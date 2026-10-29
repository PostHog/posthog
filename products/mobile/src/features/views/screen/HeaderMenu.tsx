import type { ComponentType, ReactElement } from 'react'
import { View } from 'react-native'

import { MenuItem } from '@/features/views/list/ViewsMenu'
import { FloatingCard } from '@/ui/FloatingCard'
import type { IconProps } from '@/ui/icons/types'
import { createStyles, useColors } from '@/ui/theme'
import { iconSizes } from '@/ui/tokens'
import { topOffset, useScreenInsets } from '@/ui/useScreenInsets'

/** Design-frame top of the menu: just under the chrome's 54pt More pill. */
const MENU_TOP = 120
const MENU_WIDTH = 268

export interface HeaderMenuItem {
    key: string
    label: string
    Icon: ComponentType<IconProps>
    onPress: () => void
    disabled?: boolean
    meta?: string | null
}

interface HeaderMenuProps {
    visible: boolean
    items: readonly HeaderMenuItem[]
    onClose: () => void
    testID: string
}

export function HeaderMenu({ visible, items, onClose, testID }: HeaderMenuProps): ReactElement {
    const colors = useColors()
    const styles = useStyles()
    const insets = useScreenInsets()
    return (
        <FloatingCard
            visible={visible}
            onClose={onClose}
            transformOrigin="top right"
            accessibilityLabel="More"
            testID={testID}
            style={[styles.card, { top: topOffset(insets, MENU_TOP) }]}
        >
            <View style={styles.content}>
                {items.map(({ key, label, Icon, onPress, disabled = false, meta }) => (
                    <MenuItem
                        key={key}
                        label={label}
                        meta={meta}
                        disabled={disabled}
                        onPress={() => {
                            onClose()
                            onPress()
                        }}
                        trailing={<Icon size={iconSizes.control} color={disabled ? colors.disabled : colors.ink} />}
                        testID={`${testID}-${key}`}
                    />
                ))}
            </View>
        </FloatingCard>
    )
}

const useStyles = createStyles(({ colors }) => ({
    card: {
        right: 16,
        width: MENU_WIDTH,
        borderRadius: 16,
        borderWidth: 1,
        borderColor: colors.hairline,
    },
    content: {
        padding: 6,
    },
}))
