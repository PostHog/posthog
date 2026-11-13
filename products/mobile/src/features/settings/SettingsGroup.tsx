import { Children, Fragment, isValidElement, type ReactElement, type ReactNode } from 'react'
import { Text, View } from 'react-native'

import { createStyles } from '@/ui/theme'
import { radii, type } from '@/ui/tokens'

interface SettingsGroupProps {
    title: string
    description?: string
    children: ReactNode
    footer?: string
    testID?: string
}

export function SettingsGroup({ title, description, children, footer, testID }: SettingsGroupProps): ReactElement {
    const styles = useStyles()
    const rows = Children.toArray(children)
    return (
        <View style={styles.group} testID={testID}>
            <Text style={[type.eyebrow, styles.title]}>{title.toUpperCase()}</Text>
            {description ? <Text style={styles.description}>{description}</Text> : null}
            <View style={styles.card}>
                {rows.map((row, index) => (
                    <Fragment key={isValidElement(row) && row.key !== null ? row.key : index}>
                        {index > 0 ? <View style={styles.separator} /> : null}
                        {row}
                    </Fragment>
                ))}
            </View>
            {footer ? <Text style={styles.footer}>{footer}</Text> : null}
        </View>
    )
}

const useStyles = createStyles(({ colors }) => ({
    group: {
        marginTop: 24,
    },
    title: {
        color: colors.tertiary,
        marginBottom: 8,
        paddingHorizontal: 4,
    },
    description: {
        ...type.metaSmall,
        color: colors.secondary,
        marginBottom: 8,
        paddingHorizontal: 4,
    },
    card: {
        backgroundColor: colors.surface,
        borderWidth: 1,
        borderColor: colors.border,
        borderRadius: radii.card,
        overflow: 'hidden',
    },
    separator: {
        height: 1,
        backgroundColor: colors.rowDivider,
        marginLeft: 16,
    },
    footer: {
        ...type.metaSmall,
        color: colors.secondary,
        marginTop: 8,
        paddingHorizontal: 4,
    },
}))
