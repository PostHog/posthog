import type { ReactElement } from 'react'
import { Linking, StyleSheet, Text, View } from 'react-native'

import { track } from '@/lib/analytics'
import type { EvidenceBlock } from '@/model/types'
import { PlayIcon } from '@/ui/icons/PlayIcon'
import { MonoText } from '@/ui/MonoText'
import { Pressable44 } from '@/ui/Pressable44'
import { colors, radii, type } from '@/ui/tokens'

type ReplayBlock = Extract<EvidenceBlock, { kind: 'replay' }>

export function ReplayRow({ block, reportId }: { block: ReplayBlock; reportId: string }): ReactElement {
    const countLabel = block.count === 1 ? '1 replay' : `${block.count} replays`
    return (
        <Pressable44
            onPress={() => {
                track('mobile_report_replay_opened', { report_id: reportId, replay_count: block.count })
                Linking.openURL(block.url).catch(() => undefined)
            }}
            accessibilityRole="link"
            accessibilityLabel={`Watch a session, ${countLabel}`}
            style={styles.row}
            pressedStyle={styles.pressed}
        >
            <View style={styles.left}>
                <View style={styles.play}>
                    <PlayIcon size={10} color={colors.white} />
                </View>
                <View style={styles.body}>
                    <Text style={styles.title}>Watch a session</Text>
                    <MonoText color={colors.secondary} style={styles.meta} numberOfLines={1}>
                        {block.meta}
                    </MonoText>
                </View>
            </View>
            <Text style={styles.count}>{countLabel}</Text>
        </Pressable44>
    )
}

const styles = StyleSheet.create({
    row: {
        flexDirection: 'row',
        alignItems: 'center',
        justifyContent: 'space-between',
        gap: 10,
        borderWidth: 1,
        borderColor: colors.border,
        borderRadius: radii.card,
        backgroundColor: colors.white,
        paddingVertical: 12,
        paddingHorizontal: 14,
    },
    pressed: {
        borderColor: colors.disabled,
    },
    left: {
        flex: 1,
        minWidth: 0,
        flexDirection: 'row',
        alignItems: 'center',
        gap: 10,
    },
    play: {
        width: 32,
        height: 32,
        borderRadius: 16,
        backgroundColor: colors.ink,
        alignItems: 'center',
        justifyContent: 'center',
    },
    body: {
        flex: 1,
        minWidth: 0,
    },
    title: {
        ...type.bodySmallStrong,
        color: colors.ink,
    },
    meta: {
        lineHeight: 16.8,
    },
    count: {
        fontSize: 13,
        lineHeight: 18.2,
        color: colors.secondary,
    },
})
