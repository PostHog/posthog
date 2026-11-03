import { type ReactElement, useMemo } from 'react'
import { ScrollView, Text, useWindowDimensions, View } from 'react-native'
import { Gesture, GestureDetector } from 'react-native-gesture-handler'

import type { PullRequestView } from '@/model/types'
import { BottomSheet } from '@/ui/BottomSheet'
import { CheckIcon } from '@/ui/icons/CheckIcon'
import { Pressable44 } from '@/ui/Pressable44'
import { createStyles, useColors } from '@/ui/theme'
import { iconSizes, radii, type } from '@/ui/tokens'

import { PULL_REQUEST_STATE_LABELS, pullRequestIdentity, pullRequestTitle } from './pullRequestDisplay'
import { SheetPageHeader } from './SheetPageHeader'

interface PullRequestPickerSheetProps {
    visible: boolean
    pullRequests: PullRequestView[]
    selectedUrl: string
    onClose: () => void
    onSelect: (pullRequest: PullRequestView) => void
}

export function PullRequestPickerSheet({
    visible,
    pullRequests,
    selectedUrl,
    onClose,
    onSelect,
}: PullRequestPickerSheetProps): ReactElement {
    const colors = useColors()
    const styles = useStyles()
    const { height } = useWindowDimensions()
    const listGesture = useMemo(() => Gesture.Native(), [])
    return (
        <BottomSheet
            visible={visible}
            onClose={onClose}
            scrollGesture={listGesture}
            accessibilityLabel="Pull requests"
            testID="pull-request-picker"
        >
            <SheetPageHeader title="Pull requests" onBack={onClose} testID="pull-request-picker" />
            <GestureDetector gesture={listGesture}>
                <ScrollView style={{ maxHeight: height * 0.5 }} accessibilityRole="radiogroup">
                    {pullRequests.map((pr) => (
                        <Pressable44
                            key={pr.url}
                            onPress={() => onSelect(pr)}
                            accessibilityRole="radio"
                            accessibilityLabel={pullRequestTitle(pr)}
                            accessibilityState={{ checked: pr.url === selectedUrl }}
                            pressedBackground={colors.background}
                            style={styles.row}
                            testID={`pull-request-option-${pr.number ?? pullRequests.indexOf(pr)}`}
                        >
                            <View style={styles.body}>
                                <Text style={styles.title} numberOfLines={2}>
                                    {pr.title ?? (pullRequestIdentity(pr) || pullRequestTitle(pr))}
                                </Text>
                                <Text style={styles.meta} numberOfLines={1}>
                                    {[
                                        pr.title ? pullRequestIdentity(pr) : undefined,
                                        PULL_REQUEST_STATE_LABELS[pr.state],
                                    ]
                                        .filter(Boolean)
                                        .join(' · ')}
                                </Text>
                            </View>
                            {pr.url === selectedUrl ? <CheckIcon size={iconSizes.control} /> : null}
                        </Pressable44>
                    ))}
                </ScrollView>
            </GestureDetector>
        </BottomSheet>
    )
}

const useStyles = createStyles(({ colors }) => ({
    row: {
        flexDirection: 'row',
        alignItems: 'center',
        gap: 12,
        minHeight: 64,
        paddingVertical: 10,
        paddingHorizontal: 4,
        borderRadius: radii.card,
    },
    body: { flex: 1, minWidth: 0, gap: 4 },
    title: { ...type.bodyStrong, color: colors.ink },
    meta: { ...type.meta, color: colors.muted },
}))
