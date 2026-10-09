import type { ReactElement } from 'react'
import { StyleSheet, View } from 'react-native'

import { BackChip } from '@/ui/BackChip'
import { FadeEdge } from '@/ui/FadeEdge'
import { ChevronLeftIcon } from '@/ui/icons/ChevronLeftIcon'
import { ChevronRightIcon } from '@/ui/icons/ChevronRightIcon'
import { SegmentedPill } from '@/ui/SegmentedPill'
import { layout } from '@/ui/tokens'
import { topOffset, useScreenInsets } from '@/ui/useScreenInsets'

interface TopChromeProps {
    onBack: () => void
    onPrevious?: () => void
    onNext?: () => void
}

export function TopChrome({ onBack, onPrevious, onNext }: TopChromeProps): ReactElement {
    const insets = useScreenInsets()
    return (
        <View style={[styles.chrome, { paddingTop: topOffset(insets, 58) }]}>
            <FadeEdge direction="down" solid={0.7} />
            <BackChip onPress={onBack} testID="report-back" />
            <SegmentedPill
                height={46}
                raised
                segmentWidth={44}
                segments={[
                    {
                        key: 'previous',
                        accessibilityLabel: 'Previous report',
                        onPress: () => onPrevious?.(),
                        disabled: !onPrevious,
                        testID: 'report-previous',
                        children: <ChevronLeftIcon size={15} />,
                    },
                    {
                        key: 'next',
                        accessibilityLabel: 'Next report',
                        onPress: () => onNext?.(),
                        disabled: !onNext,
                        testID: 'report-next',
                        children: <ChevronRightIcon size={15} />,
                    },
                ]}
            />
        </View>
    )
}

const styles = StyleSheet.create({
    chrome: {
        position: 'absolute',
        top: 0,
        left: 0,
        right: 0,
        zIndex: 20,
        flexDirection: 'row',
        alignItems: 'center',
        justifyContent: 'space-between',
        paddingHorizontal: layout.detailGutter,
        paddingBottom: 10,
        pointerEvents: 'box-none',
    },
})
