import type { ReactElement, ReactNode } from 'react'
import { Text, View } from 'react-native'

import type { Freshness } from '@/model/views'
import { createStyles } from '@/ui/theme'
import { radii, type } from '@/ui/tokens'

import { TileSkeleton } from '../screen/ViewSkeleton'
import type { ItemErrorKind } from '../viewsCache'

export type WebCardState = 'ready' | 'loading' | 'empty' | 'error'

const ERRORS: Record<ItemErrorKind, string> = {
    deleted: "Couldn't load this data. Pull down to try again.",
    no_access: "You don't have access to this data.",
    scope: 'Sign in again to see web analytics.',
    failed: "Couldn't load this data. Pull down to try again.",
}

/**
 * The body state of a card from its data. A snapshot without a good result yet (`lastRefreshAt` null) is not data:
 * it shows the error when its read failed, and the skeleton while a read runs.
 */
export function webCardState(
    data: { snapshot: Freshness | undefined; error: ItemErrorKind | null; updating: boolean },
    hasContent: boolean
): WebCardState {
    if (!data.snapshot?.lastRefreshAt) {
        if (data.error) {
            return 'error'
        }
        if (!data.snapshot || data.updating) {
            return 'loading'
        }
    }
    return hasContent ? 'ready' : 'empty'
}

interface WebCardProps {
    /** The title row. A string draws the plain title; a node replaces it, such as the breakdown picker. */
    title: ReactNode
    meta?: string | null
    accessory?: ReactNode
    state: WebCardState
    error: ItemErrorKind | null
    stale: boolean
    updating: boolean
    /** The skeleton's height, about the content's, so the card does not jump when its data lands. */
    loadingHeight: number
    children: ReactNode
    testID: string
}

export function WebCard({
    title,
    meta,
    accessory,
    state,
    error,
    stale,
    updating,
    loadingHeight,
    children,
    testID,
}: WebCardProps): ReactElement {
    const styles = useStyles()
    return (
        <View style={styles.card} testID={testID}>
            <View style={styles.head}>
                <View style={styles.titles}>
                    {typeof title === 'string' ? (
                        <Text style={styles.title} accessibilityRole="header" numberOfLines={1}>
                            {title}
                        </Text>
                    ) : (
                        title
                    )}
                    {meta ? (
                        <Text style={styles.meta} numberOfLines={1}>
                            {meta}
                        </Text>
                    ) : null}
                </View>
                {accessory}
            </View>
            {state === 'loading' ? (
                <View testID={`${testID}-loading`}>
                    <TileSkeleton height={loadingHeight} />
                </View>
            ) : state === 'error' ? (
                <Text style={styles.message} testID={`${testID}-error`}>
                    {ERRORS[error ?? 'failed']}
                </Text>
            ) : state === 'empty' ? (
                <Text style={styles.message} testID={`${testID}-empty`}>
                    No data for this range.
                </Text>
            ) : (
                <View style={stale ? styles.dimmed : undefined}>{children}</View>
            )}
            {updating ? <View style={styles.progress} accessibilityElementsHidden /> : null}
        </View>
    )
}

const useStyles = createStyles(({ colors }) => ({
    card: {
        padding: 14,
        borderRadius: radii.card,
        borderWidth: 1,
        borderColor: colors.hairline,
        backgroundColor: colors.surface,
        overflow: 'hidden',
    },
    head: {
        flexDirection: 'row',
        alignItems: 'flex-start',
        gap: 8,
        marginBottom: 12,
    },
    titles: {
        flex: 1,
        minWidth: 0,
    },
    title: {
        fontSize: 15,
        lineHeight: 20,
        fontWeight: '600',
        color: colors.ink,
    },
    meta: {
        ...type.meta,
        lineHeight: 18,
        color: colors.tertiary,
    },
    message: {
        ...type.metaSmall,
        color: colors.muted,
        paddingVertical: 8,
    },
    dimmed: {
        opacity: 0.5,
    },
    progress: {
        position: 'absolute',
        top: 0,
        left: 0,
        right: 0,
        height: 2,
        backgroundColor: colors.blueLight,
    },
}))
