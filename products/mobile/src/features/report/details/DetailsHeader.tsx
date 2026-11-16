import type { ReactElement } from 'react'
import { type LayoutChangeEvent, StyleSheet, View } from 'react-native'

import type { ReportView } from '@/model/types'
import { Eyebrow } from '@/ui/Eyebrow'

import { HeadlineTitle } from '../HeadlineTitle'
import { ReportByline } from '../ReportByline'

interface DetailsHeaderProps {
    report: ReportView
    /** The distance from the top of the header to the bottom of the headline, for the chrome title reveal. */
    onHeadlineBottom: (bottom: number) => void
}

export function DetailsHeader({ report, onHeadlineBottom }: DetailsHeaderProps): ReactElement {
    const onLayout = (event: LayoutChangeEvent): void => {
        const { y, height } = event.nativeEvent.layout
        onHeadlineBottom(y + height)
    }
    return (
        <View>
            <Eyebrow>Full report</Eyebrow>
            <View style={styles.headline} onLayout={onLayout}>
                <HeadlineTitle headline={report.headline} accent={report.accent} />
            </View>
            <ReportByline report={report} />
        </View>
    )
}

const styles = StyleSheet.create({
    headline: {
        marginTop: 8,
    },
})
