import type { ReactElement, ReactNode } from 'react'
import { Text, View } from 'react-native'

import { IconTile } from '@/ui/IconTile'
import { ExternalLinkIcon } from '@/ui/icons/ExternalLinkIcon'
import { FlagIcon } from '@/ui/icons/FlagIcon'
import { GlobeIcon } from '@/ui/icons/GlobeIcon'
import { Pressable44 } from '@/ui/Pressable44'
import { createStyles, useColors } from '@/ui/theme'
import { fonts, iconSizes, radii, type } from '@/ui/tokens'

import type { RolloutModel } from './detailModel'

function LinkCard({
    icon,
    title,
    titleMono = false,
    sub,
    tail,
    onPress,
    accessibilityLabel,
    testID,
}: {
    icon: ReactNode
    title: string
    titleMono?: boolean
    sub: string
    tail: ReactNode
    onPress?: () => void
    accessibilityLabel: string
    testID: string
}): ReactElement {
    const colors = useColors()
    const styles = useStyles()
    return (
        <View style={styles.card}>
            <Pressable44
                onPress={onPress}
                disabled={!onPress}
                accessibilityRole="link"
                accessibilityLabel={accessibilityLabel}
                accessibilityState={{ disabled: !onPress }}
                pressedBackground={colors.pressed}
                style={styles.row}
                testID={testID}
            >
                <IconTile muted>{icon}</IconTile>
                <View style={styles.text}>
                    <Text style={[styles.title, titleMono && styles.mono]} numberOfLines={1}>
                        {title}
                    </Text>
                    <Text style={styles.sub} numberOfLines={2}>
                        {sub}
                    </Text>
                </View>
                {tail}
            </Pressable44>
        </View>
    )
}

/** The flag and its split. Ramping stays on the web, so the row opens the flag there. */
export function RolloutRow({ model, onOpenFlag }: { model: RolloutModel; onOpenFlag?: () => void }): ReactElement {
    const colors = useColors()
    const styles = useStyles()
    return (
        <LinkCard
            icon={<FlagIcon size={17} color={colors.ink} />}
            title={model.flagKey}
            titleMono
            sub={model.line}
            accessibilityLabel={`Feature flag ${model.flagKey}, ${model.line}. Open the flag on the web`}
            onPress={onOpenFlag}
            testID="experiment-rollout"
            tail={
                <View style={styles.tail}>
                    <Text style={[styles.tailText, !onOpenFlag && styles.disabled]}>Open flag</Text>
                    <ExternalLinkIcon size={15} color={onOpenFlag ? colors.ink : colors.disabled} />
                </View>
            }
        />
    )
}

/** Says what stays on the web, and opens it there. */
export function OpenOnWebRow({
    title,
    sub,
    onPress,
}: {
    title: string
    sub: string
    onPress?: () => void
}): ReactElement {
    const colors = useColors()
    return (
        <LinkCard
            icon={<GlobeIcon size={17} color={colors.ink} />}
            title={title}
            sub={sub}
            accessibilityLabel={`${title}: ${sub}`}
            onPress={onPress}
            testID="experiment-open-web"
            tail={<ExternalLinkIcon size={iconSizes.inline} color={onPress ? colors.ink : colors.disabled} />}
        />
    )
}

const useStyles = createStyles(({ colors }) => ({
    card: {
        borderRadius: radii.card,
        borderWidth: 1,
        borderColor: colors.hairline,
        backgroundColor: colors.surface,
        overflow: 'hidden',
    },
    row: {
        flexDirection: 'row',
        alignItems: 'center',
        gap: 12,
        paddingHorizontal: 12,
        paddingVertical: 12,
    },
    text: {
        flex: 1,
        minWidth: 0,
        gap: 2,
    },
    title: {
        ...type.bodySmallStrong,
        color: colors.ink,
    },
    mono: {
        fontFamily: fonts.mono,
        fontSize: 14,
        fontWeight: '500',
    },
    sub: {
        ...type.meta,
        color: colors.secondary,
    },
    tail: {
        flexDirection: 'row',
        alignItems: 'center',
        gap: 4,
    },
    tailText: {
        ...type.meta,
        fontWeight: '600',
        color: colors.ink,
    },
    disabled: {
        color: colors.disabled,
    },
}))
