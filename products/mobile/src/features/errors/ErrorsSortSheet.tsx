import type { ReactElement } from 'react'
import { Text, View } from 'react-native'

import type { IssueSort } from '@/api/errorTracking'
import { BottomSheet } from '@/ui/BottomSheet'
import { BarChartIcon } from '@/ui/icons/BarChartIcon'
import { PersonIcon } from '@/ui/icons/PersonIcon'
import { RecordingIcon } from '@/ui/icons/RecordingIcon'
import type { IconProps } from '@/ui/icons/types'
import { OptionCard, type OptionCardItem } from '@/ui/OptionCard'
import { createStyles } from '@/ui/theme'
import { type } from '@/ui/tokens'

function OccurrencesIcon(props: IconProps): ReactElement {
    return <BarChartIcon {...props} layout="grouped" />
}

// The same order as the stats on each card.
const SORT_OPTIONS: readonly OptionCardItem<IssueSort>[] = [
    { key: 'users', label: 'Most users', Icon: PersonIcon },
    {
        key: 'sessions',
        label: 'Most sessions',
        description: 'Errors with no session ID come last',
        Icon: RecordingIcon,
    },
    { key: 'occurrences', label: 'Most occurrences', Icon: OccurrencesIcon },
]

interface ErrorsSortSheetProps {
    visible: boolean
    sort: IssueSort
    onSelect: (sort: IssueSort) => void
    onClose: () => void
}

/** One tap applies the sort and closes the sheet, so it has no Done button. */
export function ErrorsSortSheet({ visible, sort, onSelect, onClose }: ErrorsSortSheetProps): ReactElement {
    const styles = useStyles()
    return (
        <BottomSheet
            visible={visible}
            onClose={onClose}
            paddingHorizontal={20}
            accessibilityLabel="Sort by"
            testID="errors-sort-sheet"
        >
            <View style={styles.head}>
                <Text style={styles.title} accessibilityRole="header">
                    Sort by
                </Text>
            </View>
            <View style={styles.body}>
                <OptionCard
                    options={SORT_OPTIONS}
                    selected={sort}
                    onSelect={(next) => {
                        onSelect(next)
                        onClose()
                    }}
                    testIDPrefix="errors-sort"
                />
            </View>
        </BottomSheet>
    )
}

const useStyles = createStyles(({ colors }) => ({
    head: {
        paddingTop: 14,
        paddingBottom: 8,
        paddingHorizontal: 4,
    },
    title: {
        ...type.sheetTitle,
        color: colors.ink,
    },
    body: {
        paddingTop: 4,
    },
}))
