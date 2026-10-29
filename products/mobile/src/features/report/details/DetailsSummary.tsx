import type { ReactElement } from 'react'
import { StyleSheet, View } from 'react-native'

import { ReportMarkdown } from './ReportMarkdown'

export function DetailsSummary({ summary, reportId }: { summary: string; reportId: string }): ReactElement {
    return (
        <View style={styles.summary} testID="report-details-summary">
            <ReportMarkdown text={summary} reportId={reportId} tone="summary" />
        </View>
    )
}

const styles = StyleSheet.create({
    summary: {
        marginTop: 16,
    },
})
