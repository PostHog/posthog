import { type ReactElement, useRef, useState } from 'react'
import { Modal, Text, useWindowDimensions, View } from 'react-native'

import { FloatingCard } from '@/ui/FloatingCard'
import { CheckIcon } from '@/ui/icons/CheckIcon'
import { ChevronDownIcon } from '@/ui/icons/ChevronDownIcon'
import { Pressable44 } from '@/ui/Pressable44'
import { createStyles, useColors } from '@/ui/theme'
import { iconSizes, radii, type } from '@/ui/tokens'
import { useScreenInsets } from '@/ui/useScreenInsets'

import { CLOUD_REGIONS, type CloudRegion } from './regions'

interface RegionSelectProps {
    value: CloudRegion['id']
    onChange: (region: CloudRegion['id']) => void
    disabled: boolean
}

interface Anchor {
    x: number
    y: number
    width: number
    height: number
}

export function RegionSelect({ value, onChange, disabled }: RegionSelectProps): ReactElement {
    const colors = useColors()
    const styles = useStyles()
    const trigger = useRef<View>(null)
    const [anchor, setAnchor] = useState<Anchor | null>(null)
    const { height: windowHeight } = useWindowDimensions()
    const insets = useScreenInsets()
    const selected = CLOUD_REGIONS.find((region) => region.id === value) ?? CLOUD_REGIONS[0]
    const close = (): void => setAnchor(null)
    const open = (): void => {
        trigger.current?.measureInWindow((x, y, width, height) => setAnchor({ x, y, width, height }))
    }

    return (
        <>
            <Pressable44
                ref={trigger}
                onPress={open}
                disabled={disabled}
                accessibilityLabel="Data region"
                accessibilityValue={{ text: selected.label }}
                accessibilityState={{ expanded: anchor !== null, disabled }}
                aria-haspopup="dialog"
                pressedBackground={colors.sunken}
                style={styles.trigger}
                testID="sign-in-region"
            >
                <Text style={styles.label} numberOfLines={1}>
                    {selected.flag} {selected.label}
                </Text>
                <ChevronDownIcon size={iconSizes.inline} color={colors.secondary} />
            </Pressable44>
            {anchor ? (
                <Modal transparent visible onRequestClose={close} statusBarTranslucent navigationBarTranslucent>
                    <View style={styles.overlay}>
                        <FloatingCard
                            visible
                            onClose={close}
                            accessibilityLabel="Data region"
                            testID="sign-in-region-menu"
                            style={[
                                styles.menu,
                                {
                                    left: anchor.x,
                                    top: Math.max(
                                        insets.top,
                                        Math.min(
                                            anchor.y + anchor.height + 6,
                                            windowHeight - insets.bottom - (CLOUD_REGIONS.length * 48 + 14)
                                        )
                                    ),
                                    width: anchor.width,
                                },
                            ]}
                        >
                            <View accessibilityRole="list">
                                {CLOUD_REGIONS.map((region) => (
                                    <Pressable44
                                        key={region.id}
                                        onPress={() => {
                                            onChange(region.id)
                                            close()
                                        }}
                                        accessibilityRole="radio"
                                        accessibilityLabel={region.label}
                                        accessibilityState={{ checked: region.id === value }}
                                        aria-checked={region.id === value}
                                        pressedBackground={colors.sunken}
                                        style={styles.option}
                                        testID={`region-${region.id}`}
                                    >
                                        <Text style={styles.label} numberOfLines={1}>
                                            {region.flag} {region.label}
                                        </Text>
                                        {region.id === value ? (
                                            <CheckIcon size={iconSizes.control} color={colors.ink} />
                                        ) : null}
                                    </Pressable44>
                                ))}
                            </View>
                        </FloatingCard>
                    </View>
                </Modal>
            ) : null}
        </>
    )
}

const useStyles = createStyles(({ colors }) => ({
    trigger: {
        minHeight: 48,
        paddingHorizontal: 16,
        paddingVertical: 12,
        flexDirection: 'row',
        alignItems: 'center',
        gap: 12,
        borderWidth: 1,
        borderColor: colors.border,
        borderRadius: radii.card,
        backgroundColor: colors.surface,
    },
    label: {
        ...type.body,
        color: colors.ink,
        flex: 1,
    },
    overlay: {
        flex: 1,
    },
    menu: {
        padding: 6,
        borderWidth: 1,
        borderColor: colors.border,
        borderRadius: radii.card,
    },
    option: {
        minHeight: 48,
        paddingHorizontal: 10,
        paddingVertical: 12,
        flexDirection: 'row',
        alignItems: 'center',
        gap: 12,
        borderRadius: radii.menuRow,
    },
}))
