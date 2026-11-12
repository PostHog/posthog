import type { ReactElement } from 'react'
import { View } from 'react-native'

import { createStyles } from '@/ui/theme'

import { CardTitleText, FieldHelp, RadioCard } from './FinishSheetSections'

interface RepositoryPickerProps {
    candidates: readonly string[]
    value: string | null
    onChange: (repository: string) => void
    disabled: boolean
}

/**
 * With several connected repositories and none saved, the server skips the cleanup PR rather than guess, so the sheet
 * needs a pick. The web's "Use this repository for all experiments in this project" checkbox is left out: it needs
 * `project:write`, which the app does not request.
 */
export function RepositoryPicker({ candidates, value, onChange, disabled }: RepositoryPickerProps): ReactElement {
    const styles = useStyles()
    return (
        <View style={styles.picker} testID="experiment-cleanup-repository">
            <FieldHelp>Several repositories are connected. Pick the one that holds this flag's code.</FieldHelp>
            <View style={styles.group} accessibilityRole="radiogroup" accessibilityLabel="Repository">
                {candidates.map((repository) => (
                    <RadioCard
                        key={repository}
                        selected={value === repository}
                        onPress={() => onChange(repository)}
                        disabled={disabled}
                        accessibilityLabel={repository}
                        title={<CardTitleText mono>{repository}</CardTitleText>}
                        testID={`experiment-cleanup-repository-${repository}`}
                    />
                ))}
            </View>
        </View>
    )
}

const useStyles = createStyles(() => ({
    picker: {
        marginTop: 12,
    },
    group: {
        gap: 6,
    },
}))
