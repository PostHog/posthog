import type { ReactElement } from 'react'
import { ActivityIndicator, Text, View } from 'react-native'

import { ExternalLinkIcon } from '@/ui/icons/ExternalLinkIcon'
import { Pressable44 } from '@/ui/Pressable44'
import { createStyles, useColors } from '@/ui/theme'
import { iconSizes, radii, type } from '@/ui/tokens'

interface AiOrgNoticeProps {
    /** `not_approved`: an admin has not allowed third-party AI. `unknown`: the app could not load the setting. */
    reason: 'not_approved' | 'unknown'
    organizationName: string | null
    canApprove?: boolean
    onCancel?: () => void
    /** Null hides Open settings. */
    onOpenSettings: (() => void) | null
    onCheckAgain: () => void
    checking: boolean
}

function copyFor(
    reason: AiOrgNoticeProps['reason'],
    organizationName: string | null,
    canApprove: boolean
): { title: string; body: string } {
    if (reason === 'unknown') {
        return {
            title: "Couldn't check PostHog AI access",
            body: 'Check your connection, then try again.',
        }
    }
    return {
        title: `PostHog AI is off for ${organizationName ?? 'this organization'}`,
        body: canApprove
            ? 'As an admin or owner, you can allow third-party AI services in organization settings.'
            : 'Ask an admin or owner to allow third-party AI services in organization settings, then check again.',
    }
}

/** Takes the composer's place while the organization does not allow PostHog AI, as the web blocks its chat. */
export function AiOrgNotice({
    reason,
    organizationName,
    canApprove = false,
    onCancel,
    onOpenSettings,
    onCheckAgain,
    checking,
}: AiOrgNoticeProps): ReactElement {
    const colors = useColors()
    const styles = useStyles()
    const copy = copyFor(reason, organizationName, canApprove)
    return (
        <View style={styles.notice} testID="chat-ai-org-notice">
            <Text style={styles.title} accessibilityRole="header">
                {copy.title}
            </Text>
            <Text style={styles.body}>{copy.body}</Text>
            <View style={styles.actions}>
                {onOpenSettings ? (
                    <Pressable44
                        onPress={onOpenSettings}
                        pressedBackground={colors.inkHover}
                        style={[styles.button, styles.primary]}
                        testID="chat-ai-org-settings"
                    >
                        <ExternalLinkIcon size={iconSizes.inline} color={colors.onInk} />
                        <Text style={styles.primaryText}>Open settings</Text>
                    </Pressable44>
                ) : null}
                <Pressable44
                    onPress={onCheckAgain}
                    disabled={checking}
                    accessibilityState={{ busy: checking, disabled: checking }}
                    pressedBackground={onOpenSettings ? colors.sunken : colors.inkHover}
                    style={[styles.button, onOpenSettings ? styles.secondary : styles.primary]}
                    testID="chat-ai-org-check-again"
                >
                    {checking ? (
                        <ActivityIndicator color={onOpenSettings ? colors.ink : colors.onInk} />
                    ) : (
                        <Text style={onOpenSettings ? styles.secondaryText : styles.primaryText}>Check again</Text>
                    )}
                </Pressable44>
            </View>
            {onCancel ? (
                <Pressable44
                    onPress={onCancel}
                    accessibilityLabel="Not now"
                    style={styles.cancel}
                    testID="ai-approval-cancel"
                >
                    <Text style={styles.secondaryText}>Not now</Text>
                </Pressable44>
            ) : null}
        </View>
    )
}

const useStyles = createStyles(({ colors }) => ({
    notice: {
        marginHorizontal: 16,
        marginTop: 8,
        marginBottom: 8,
        padding: 16,
        gap: 6,
        borderRadius: radii.card,
        borderWidth: 1,
        borderColor: colors.hairline,
        backgroundColor: colors.background,
    },
    title: {
        ...type.bodyStrong,
        color: colors.ink,
    },
    body: {
        ...type.bodySmall,
        color: colors.muted,
    },
    cancel: { alignItems: 'center', justifyContent: 'center', height: 44 },
    actions: {
        flexDirection: 'row',
        gap: 10,
        marginTop: 10,
    },
    button: {
        flex: 1,
        height: 44,
        flexDirection: 'row',
        gap: 8,
        borderRadius: radii.pill,
        alignItems: 'center',
        justifyContent: 'center',
    },
    primary: {
        backgroundColor: colors.ink,
    },
    primaryText: {
        ...type.buttonSmall,
        color: colors.onInk,
    },
    secondary: {
        borderWidth: 1,
        borderColor: colors.border,
        backgroundColor: colors.surface,
    },
    secondaryText: {
        ...type.buttonSmall,
        color: colors.ink,
    },
}))
