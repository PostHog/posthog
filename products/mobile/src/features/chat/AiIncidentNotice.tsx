import type { ReactElement } from 'react'
import { Linking, Text } from 'react-native'

import type { PostHogStatus } from '@/features/status/usePostHogStatus'
import { ExternalLinkIcon } from '@/ui/icons/ExternalLinkIcon'
import { WarningIcon } from '@/ui/icons/WarningIcon'
import { Pressable44 } from '@/ui/Pressable44'
import { createStyles, useColors } from '@/ui/theme'
import { radii, type } from '@/ui/tokens'

export function AiIncidentNotice({ incident }: { incident: NonNullable<PostHogStatus['aiIncident']> }): ReactElement {
    const styles = useStyles()
    const colors = useColors()
    const label = `PostHog AI incident (${incident.status}) · ${incident.title}`
    return (
        <Pressable44
            accessibilityRole="link"
            accessibilityLabel={label}
            accessibilityHint="Opens the incident update"
            onPress={() => void Linking.openURL(incident.url).catch(() => undefined)}
            pressedBackground={colors.sunken}
            style={styles.notice}
            testID="chat-ai-incident"
        >
            <WarningIcon size={18} color={colors[incident.color]} />
            <Text style={styles.text} numberOfLines={2}>
                {label}
            </Text>
            <ExternalLinkIcon size={16} color={colors.muted} />
        </Pressable44>
    )
}

const useStyles = createStyles(({ colors }) => ({
    notice: {
        marginHorizontal: 16,
        marginBottom: 6,
        paddingHorizontal: 12,
        paddingVertical: 6,
        minHeight: 44,
        flexDirection: 'row',
        alignItems: 'center',
        gap: 8,
        backgroundColor: colors.background,
        borderColor: colors.hairline,
        borderWidth: 1,
        borderRadius: radii.card,
    },
    text: { ...type.meta, flex: 1, color: colors.ink },
}))
