import { useRouter } from 'expo-router'
import type { ReactElement } from 'react'
import { Linking, Text, View } from 'react-native'

import { useDataMode } from '@/demo/demoMode'
import { track } from '@/lib/analytics'
import type { EvidenceBlock } from '@/model/types'
import { PlayIcon } from '@/ui/icons/PlayIcon'
import { MonoText } from '@/ui/MonoText'
import { Pressable44 } from '@/ui/Pressable44'
import { createStyles, useColors } from '@/ui/theme'
import { radii, type } from '@/ui/tokens'

type ReplayBlock = Extract<EvidenceBlock, { kind: 'replay' }>

export function ReplayRow({ block, reportId }: { block: ReplayBlock; reportId: string }): ReactElement {
    const styles = useStyles()
    const colors = useColors()
    const router = useRouter()
    const demo = useDataMode() === 'demo'
    const countLabel = block.count === 1 ? '1 replay' : `${block.count} replays`
    return (
        <Pressable44
            onPress={() => {
                track('mobile_report_replay_opened', { report_id: reportId, replay_count: block.count })
                if (demo) {
                    // Demo sessions exist in no project, so the session screen would have nothing to load.
                    Linking.openURL(block.url).catch(() => undefined)
                    return
                }
                router.push({
                    pathname: '/replay/[sessionId]',
                    params: {
                        sessionId: block.sessionId,
                        source: 'report',
                        ...(block.t !== undefined ? { t: String(block.t) } : {}),
                    },
                })
            }}
            accessibilityRole="button"
            accessibilityLabel={`See the moment, ${countLabel}`}
            style={styles.row}
            pressedStyle={styles.pressed}
        >
            <View style={styles.left}>
                <View style={styles.play}>
                    <PlayIcon size={10} color={colors.onInk} />
                </View>
                <View style={styles.body}>
                    <Text style={styles.title}>See the moment</Text>
                    <MonoText color={colors.secondary} style={styles.meta} numberOfLines={1}>
                        {block.meta}
                    </MonoText>
                </View>
            </View>
            <Text style={styles.count}>{countLabel}</Text>
        </Pressable44>
    )
}

const useStyles = createStyles(({ colors }) => ({
    row: {
        flexDirection: 'row',
        alignItems: 'center',
        justifyContent: 'space-between',
        gap: 10,
        borderWidth: 1,
        borderColor: colors.border,
        borderRadius: radii.card,
        backgroundColor: colors.surface,
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
}))
