import * as Clipboard from 'expo-clipboard'
import { type ReactElement, useEffect, useRef, useState } from 'react'
import { StyleSheet, Text, View } from 'react-native'

import { POSTHOG_AGENT } from '@/model/agent'
import type { ReportView } from '@/model/types'
import { BottomSheet } from '@/ui/BottomSheet'
import { CopyIcon } from '@/ui/icons/CopyIcon'
import { PlusSquareIcon } from '@/ui/icons/PlusSquareIcon'
import { Pressable44 } from '@/ui/Pressable44'
import { colors, fonts, radii, type } from '@/ui/tokens'

const COPIED_MS = 1600

interface HandoffSheetProps {
    visible: boolean
    report: ReportView
    onClose: () => void
    onHandOff: () => void
    pending: boolean
}

export function HandoffSheet({ visible, report, onClose, onHandOff, pending }: HandoffSheetProps): ReactElement {
    const [copied, setCopied] = useState(false)
    const timer = useRef<ReturnType<typeof setTimeout> | null>(null)

    useEffect(
        () => () => {
            if (timer.current) {
                clearTimeout(timer.current)
            }
        },
        []
    )

    const copyPrompt = async (): Promise<void> => {
        await Clipboard.setStringAsync(report.prompt).catch(() => undefined)
        setCopied(true)
        if (timer.current) {
            clearTimeout(timer.current)
        }
        timer.current = setTimeout(() => setCopied(false), COPIED_MS)
    }

    return (
        <BottomSheet visible={visible} onClose={onClose} accessibilityLabel="Hand off to" testID="handoff-sheet">
            <View style={styles.titleRow}>
                <Text style={styles.title}>Hand off to</Text>
                <Text style={styles.hint}>Tap to send</Text>
            </View>
            <View style={styles.agents}>
                <Pressable44
                    onPress={onHandOff}
                    disabled={pending}
                    haptic="light"
                    accessibilityLabel={`Hand off to ${POSTHOG_AGENT.name}`}
                    accessibilityState={{ busy: pending, disabled: pending }}
                    style={styles.agent}
                    pressedStyle={styles.agentPressed}
                    testID="handoff-agent-posthog"
                >
                    <View style={styles.mark}>
                        <Text style={styles.markText}>{POSTHOG_AGENT.mark}</Text>
                    </View>
                    <View style={styles.agentBody}>
                        <Text style={styles.agentName}>{POSTHOG_AGENT.name}</Text>
                        <Text style={styles.agentMeta}>PostHog agent · opens a PR in your repo</Text>
                    </View>
                </Pressable44>
            </View>
            <View style={styles.context}>
                <PlusSquareIcon size={15} color={colors.tertiary} />
                <Text style={styles.contextText}>{report.contextNote}</Text>
            </View>
            <Pressable44
                onPress={() => void copyPrompt()}
                pressedBackground={colors.background}
                style={styles.copy}
                accessibilityLabel={copied ? 'Copied' : 'Copy prompt'}
                testID="copy-prompt"
            >
                <CopyIcon size={16} color={colors.muted} />
                <Text style={styles.copyText}>{copied ? 'Copied' : 'Copy prompt'}</Text>
            </Pressable44>
        </BottomSheet>
    )
}

const styles = StyleSheet.create({
    titleRow: {
        marginTop: 18,
        flexDirection: 'row',
        alignItems: 'baseline',
        justifyContent: 'space-between',
        paddingHorizontal: 4,
    },
    title: {
        ...type.sheetTitle,
        color: colors.ink,
    },
    hint: {
        ...type.metaSmall,
        color: colors.tertiary,
    },
    agents: {
        marginTop: 12,
        gap: 4,
    },
    agent: {
        flexDirection: 'row',
        alignItems: 'center',
        gap: 14,
        // 60pt content box plus 8pt padding and a 1pt border on each side.
        minHeight: 78,
        paddingVertical: 8,
        paddingHorizontal: 12,
        borderRadius: radii.card,
        backgroundColor: colors.background,
        borderWidth: 1,
        borderColor: colors.border,
    },
    agentPressed: {
        borderColor: colors.disabled,
    },
    mark: {
        width: 38,
        height: 38,
        borderRadius: radii.tile,
        backgroundColor: colors.ink,
        alignItems: 'center',
        justifyContent: 'center',
    },
    markText: {
        fontFamily: fonts.mono,
        fontSize: 13,
        fontWeight: '600',
        color: colors.white,
    },
    agentBody: {
        flex: 1,
        minWidth: 0,
    },
    agentName: {
        ...type.bodyStrong,
        color: colors.ink,
    },
    agentMeta: {
        ...type.metaSmall,
        color: colors.muted,
        marginTop: 1,
    },
    context: {
        marginTop: 14,
        flexDirection: 'row',
        alignItems: 'center',
        gap: 10,
        paddingHorizontal: 4,
    },
    contextText: {
        ...type.metaSmall,
        color: colors.muted,
        flex: 1,
    },
    copy: {
        marginTop: 16,
        height: 48,
        flexDirection: 'row',
        alignItems: 'center',
        justifyContent: 'center',
        gap: 8,
        borderWidth: 1,
        borderColor: colors.border,
        borderRadius: radii.card,
        backgroundColor: colors.white,
    },
    copyText: {
        ...type.buttonSmall,
        color: colors.ink,
    },
})
