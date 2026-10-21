import type { ReactElement } from 'react'
import { StyleSheet, View } from 'react-native'

import { colors } from '@/ui/tokens'

import { TextLinkRow } from '../TextLinkRow'
import { openDetailsLink } from './openDetailsLink'

export function DetailsFooter({ webUrl, reportId }: { webUrl: string; reportId: string }): ReactElement {
    return (
        <View style={styles.footer}>
            <TextLinkRow
                label="Open in PostHog"
                external
                onPress={() => openDetailsLink(webUrl, reportId, 'web')}
                testID="report-details-open-web"
            />
        </View>
    )
}

const styles = StyleSheet.create({
    footer: {
        marginTop: 24,
        paddingTop: 12,
        borderTopWidth: 1,
        borderTopColor: colors.border,
    },
})
