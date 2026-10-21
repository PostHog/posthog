import type { ReactElement } from 'react'
import { Linking, Text, View } from 'react-native'

import { safeHttpsUrl } from '@/lib/urls'
import { ExternalLinkIcon } from '@/ui/icons/ExternalLinkIcon'
import { Pressable44 } from '@/ui/Pressable44'
import { createStyles, useColors } from '@/ui/theme'
import { radii, type } from '@/ui/tokens'

import { trackViewOpenedInWeb } from './analytics'
import { useViewsContext } from './useViewsContext'
import { viewWebUrl } from './webLinks'

/** A kind the phone has no renderer for yet, such as a funnel or retention: the web shows it. */
export function OpensOnWeb({ shortId }: { shortId: string | null }): ReactElement {
    const colors = useColors()
    const styles = useStyles()
    const { scope } = useViewsContext()
    const url = shortId ? viewWebUrl(scope, `/insights/${shortId}`) : undefined
    const safe = url ? safeHttpsUrl(url) : undefined
    return (
        <View style={styles.web} testID="view-opens-on-web">
            <Text style={styles.webText}>This chart opens on the web.</Text>
            <Pressable44
                onPress={() => {
                    if (!safe) {
                        return
                    }
                    trackViewOpenedInWeb({ viewType: 'insight', reason: 'web_only' })
                    Linking.openURL(safe).catch(() => undefined)
                }}
                disabled={!safe}
                style={styles.webButton}
                pressedBackground={colors.pressed}
            >
                <ExternalLinkIcon size={16} color={safe ? colors.ink : colors.disabled} />
                <Text style={[styles.webButtonText, !safe && styles.disabledText]}>
                    {safe ? 'Open on web' : 'Not available in the demo'}
                </Text>
            </Pressable44>
        </View>
    )
}

const useStyles = createStyles(({ colors }) => ({
    web: {
        gap: 10,
        alignItems: 'flex-start',
    },
    webText: {
        ...type.bodySmall,
        color: colors.muted,
    },
    webButton: {
        height: 36,
        flexDirection: 'row',
        alignItems: 'center',
        gap: 8,
        paddingLeft: 12,
        paddingRight: 14,
        borderRadius: radii.pill,
        borderWidth: 1,
        borderColor: colors.border,
        backgroundColor: colors.surface,
    },
    webButtonText: {
        fontSize: 14,
        fontWeight: '600',
        color: colors.ink,
    },
    disabledText: {
        color: colors.disabled,
    },
}))
