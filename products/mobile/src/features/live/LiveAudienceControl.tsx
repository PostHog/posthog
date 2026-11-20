import { type ReactElement, useState } from 'react'
import { Text, View } from 'react-native'

import { HeaderMenu } from '@/features/views/screen/HeaderMenu'
import { ChevronDownIcon } from '@/ui/icons/ChevronDownIcon'
import { GlobeIcon } from '@/ui/icons/GlobeIcon'
import { PhoneIcon } from '@/ui/icons/PhoneIcon'
import { Pressable44 } from '@/ui/Pressable44'
import { createStyles, useColors } from '@/ui/theme'
import { radii, type } from '@/ui/tokens'

import { trackLiveAudienceChanged } from './analytics'
import { useLivePreference } from './livePreference'

const OPTIONS = [
    { key: 'all', label: 'All', Icon: GlobeIcon },
    { key: 'web', label: 'Web', Icon: GlobeIcon },
    { key: 'mobile', label: 'Mobile', Icon: PhoneIcon },
] as const

export function LiveAudienceControl(): ReactElement {
    const styles = useStyles()
    const colors = useColors()
    const [open, setOpen] = useState(false)
    const { preference, setPreference } = useLivePreference()
    const selected = OPTIONS.find((option) => option.key === preference)?.label ?? 'All'
    return (
        <View>
            <Pressable44
                onPress={() => setOpen(true)}
                accessibilityLabel={`Live view: ${selected}. Change view`}
                pressedBackground={colors.pressed}
                style={styles.button}
                testID="live-audience-control"
            >
                {preference === 'all' ? <GlobeIcon size={16} color={colors.ink} /> : null}
                <Text style={styles.buttonText}>{selected}</Text>
                <ChevronDownIcon size={14} color={colors.secondary} />
            </Pressable44>
            <HeaderMenu
                visible={open}
                onClose={() => setOpen(false)}
                testID="live-audience-menu"
                items={OPTIONS.map((option) => ({
                    ...option,
                    meta: option.key === preference ? 'Selected' : null,
                    onPress: () => {
                        if (option.key !== preference) {
                            trackLiveAudienceChanged({ preference: option.key })
                            setPreference(option.key)
                        }
                    },
                }))}
            />
        </View>
    )
}

const useStyles = createStyles(({ colors }) => ({
    button: {
        minHeight: 44,
        paddingHorizontal: 14,
        flexDirection: 'row',
        alignItems: 'center',
        gap: 8,
        borderRadius: radii.pill,
    },
    buttonText: { ...type.buttonSmall, color: colors.ink },
}))
