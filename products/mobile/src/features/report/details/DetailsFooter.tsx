import type { ReactElement } from 'react'
import { View } from 'react-native'

import { createStyles } from '@/ui/theme'

import { TextLinkRow } from '../TextLinkRow'
import { openDetailsLink } from './openDetailsLink'

export function DetailsFooter({ webUrl, reportId }: { webUrl: string; reportId: string }): ReactElement {
    const styles = useStyles()
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

const useStyles = createStyles(({ colors }) => ({
    footer: {
        marginTop: 24,
        paddingTop: 12,
        borderTopWidth: 1,
        borderTopColor: colors.border,
    },
}))
