import { type ReactElement, useEffect } from 'react'
import { Text, View } from 'react-native'
import { openPostHogUrl } from '@/lib/sessionHandoff'

import { safeHttpsUrl } from '@/lib/urls'
import type { ViewKind } from '@/model/views'
import { BottomSheet } from '@/ui/BottomSheet'
import { ExternalLinkIcon } from '@/ui/icons/ExternalLinkIcon'
import { PinIcon } from '@/ui/icons/PinIcon'
import { Pressable44 } from '@/ui/Pressable44'
import { createStyles, useColors } from '@/ui/theme'
import { radii, type } from '@/ui/tokens'

import { trackViewMoreOpened, trackViewOpenedInWeb } from '../analytics'

interface ViewMoreSheetProps {
    visible: boolean
    onClose: () => void
    /** The view's web page. Undefined in demo mode, which has no project on the web. */
    webUrl: string | undefined
    viewType: ViewKind
    /** "Pin to navigation" or "Unpin from navigation", for a view that can sit in the nav pill. */
    navPin?: { pinned: boolean; onToggle: () => void }
}

/** The view's More menu. The web has the full editor, so the menu hands off to it. */
export function ViewMoreSheet({ visible, onClose, webUrl, viewType, navPin }: ViewMoreSheetProps): ReactElement {
    const colors = useColors()
    const styles = useStyles()
    const safe = webUrl ? safeHttpsUrl(webUrl) : undefined
    useEffect(() => {
        if (visible) {
            trackViewMoreOpened({ viewType })
        }
    }, [visible, viewType])
    return (
        <BottomSheet
            visible={visible}
            onClose={onClose}
            paddingHorizontal={20}
            accessibilityLabel="More"
            testID="view-more-sheet"
        >
            <View style={styles.rows}>
                {navPin ? (
                    <Pressable44
                        onPress={() => {
                            onClose()
                            navPin.onToggle()
                        }}
                        style={styles.row}
                        pressedBackground={colors.background}
                        accessibilityLabel={navPin.pinned ? 'Unpin from navigation' : 'Pin to navigation'}
                        testID={navPin.pinned ? 'view-nav-unpin' : 'view-nav-pin'}
                    >
                        <PinIcon size={20} filled={navPin.pinned} color={colors.ink} />
                        <View style={styles.rowText}>
                            <Text style={styles.label}>
                                {navPin.pinned ? 'Unpin from navigation' : 'Pin to navigation'}
                            </Text>
                        </View>
                    </Pressable44>
                ) : null}
                <Pressable44
                    onPress={() => {
                        if (!safe) {
                            return
                        }
                        trackViewOpenedInWeb({ viewType, reason: 'action' })
                        openPostHogUrl(safe).catch(() => undefined)
                        onClose()
                    }}
                    disabled={!safe}
                    style={styles.row}
                    pressedBackground={colors.background}
                    testID="view-open-web"
                >
                    <ExternalLinkIcon size={20} color={safe ? colors.ink : colors.disabled} />
                    <View style={styles.rowText}>
                        <Text style={[styles.label, !safe && styles.disabled]}>Open on web</Text>
                        {safe ? null : <Text style={styles.sub}>Not available in the demo</Text>}
                    </View>
                </Pressable44>
            </View>
        </BottomSheet>
    )
}

const useStyles = createStyles(({ colors }) => ({
    rows: {
        marginTop: 12,
    },
    row: {
        flexDirection: 'row',
        alignItems: 'center',
        gap: 14,
        minHeight: 56,
        paddingHorizontal: 4,
        borderRadius: radii.card,
    },
    rowText: {
        flex: 1,
    },
    label: {
        ...type.label,
        color: colors.ink,
    },
    disabled: {
        color: colors.disabled,
    },
    sub: {
        ...type.metaSmall,
        color: colors.tertiary,
    },
}))
