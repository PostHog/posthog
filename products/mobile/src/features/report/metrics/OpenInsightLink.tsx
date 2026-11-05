import type { ReactElement } from 'react'
import { Text } from 'react-native'

import { ChevronRightIcon } from '@/ui/icons/ChevronRightIcon'
import { Pressable44 } from '@/ui/Pressable44'
import { createStyles, useColors } from '@/ui/theme'
import { iconSizes, type } from '@/ui/tokens'

import { type InsightSource, openInsight } from './openInsight'

interface OpenInsightLinkProps {
    url: string
    reportId: string
    source: InsightSource
    /** What the link opens, for screen readers: "Open insight, Errors by browser". */
    title: string
    testID?: string
}

export function OpenInsightLink({ url, reportId, source, title, testID }: OpenInsightLinkProps): ReactElement {
    const styles = useStyles()
    const colors = useColors()
    return (
        <Pressable44
            onPress={() => openInsight(url, reportId, source)}
            accessibilityRole="link"
            accessibilityLabel={`Open insight, ${title}`}
            style={styles.link}
            pressedStyle={styles.pressed}
            testID={testID}
        >
            <Text style={styles.label}>Open insight</Text>
            <ChevronRightIcon size={iconSizes.small} color={colors.blue} strokeWidth={2.6} />
        </Pressable44>
    )
}

const useStyles = createStyles(({ colors }) => ({
    link: {
        flexDirection: 'row',
        alignItems: 'center',
        gap: 4,
        flexShrink: 0,
    },
    pressed: {
        opacity: 0.6,
    },
    label: {
        ...type.meta,
        fontWeight: '600',
        color: colors.blue,
    },
}))
