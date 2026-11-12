import { type ReactElement, useEffect, useMemo, useRef, useState } from 'react'
import type { ScrollViewInstance } from 'react-native'
import { View } from 'react-native'
import { Gesture, GestureDetector } from 'react-native-gesture-handler'
import { useReanimatedKeyboardAnimation } from 'react-native-keyboard-controller'
import Animated from 'react-native-reanimated'

import type { ExperimentApi, ExperimentConclusionApi } from '@/api/experiments'
import { actionErrorMessage } from '@/lib/errors'
import { BottomSheet } from '@/ui/BottomSheet'
import { createStyles } from '@/ui/theme'

import {
    CommentField,
    ConclusionRadios,
    FieldLabel,
    SheetDescription,
    SheetError,
    SheetFooter,
    SheetTitle,
} from './FinishSheetSections'
import { COMMENT_MAX_LENGTH, editConclusionDescription } from './finishModel'

export interface ConclusionEdit {
    conclusion: ExperimentConclusionApi
    comment: string
}

interface EditConclusionSheetProps {
    visible: boolean
    experiment: ExperimentApi
    pending: boolean
    onClose: () => void
    /** Rejects with the server's error, which the sheet shows above the footer. */
    onConfirm: (edit: ConclusionEdit) => Promise<void>
}

/** The web's Edit conclusion modal. The flag does not change. */
export function EditConclusionSheet({
    visible,
    experiment,
    pending,
    onClose,
    onConfirm,
}: EditConclusionSheetProps): ReactElement {
    const styles = useStyles()
    const keyboard = useReanimatedKeyboardAnimation()
    const scrollGesture = useMemo(() => Gesture.Native(), [])
    const scroll = useRef<ScrollViewInstance>(null)
    const [conclusion, setConclusion] = useState<ExperimentConclusionApi | null>(experiment.conclusion ?? null)
    const [comment, setComment] = useState(experiment.conclusion_comment ?? '')
    const [error, setError] = useState<string | null>(null)

    const wasVisible = useRef(false)
    useEffect(() => {
        if (visible && !wasVisible.current) {
            setConclusion(experiment.conclusion ?? null)
            setComment(experiment.conclusion_comment ?? '')
            setError(null)
        }
        wasVisible.current = visible
    }, [visible, experiment.conclusion, experiment.conclusion_comment])

    const save = (): void => {
        if (!conclusion || pending) {
            return
        }
        setError(null)
        onConfirm({ conclusion, comment }).catch((saveError: unknown) => setError(actionErrorMessage(saveError)))
    }

    return (
        <BottomSheet
            visible={visible}
            onClose={onClose}
            scrollGesture={scrollGesture}
            keyboardHeight={keyboard.height}
            accessibilityLabel="Edit conclusion"
            testID="experiment-edit-conclusion-sheet"
        >
            <View style={styles.content}>
                <GestureDetector gesture={scrollGesture}>
                    <Animated.ScrollView ref={scroll} keyboardShouldPersistTaps="handled" style={styles.scroll}>
                        <SheetTitle>Edit conclusion</SheetTitle>
                        <SheetDescription>{editConclusionDescription(experiment)}</SheetDescription>
                        <FieldLabel label="Conclusion" />
                        <ConclusionRadios
                            value={conclusion}
                            suggested={null}
                            onChange={setConclusion}
                            disabled={pending}
                            testID="experiment-edit-conclusion"
                        />
                        <FieldLabel label="Comment" optional />
                        <CommentField
                            value={comment}
                            onChange={(value) => setComment(value.slice(0, COMMENT_MAX_LENGTH))}
                            editable={!pending}
                            onFocus={() => scroll.current?.scrollToEnd({ animated: true })}
                            testID="experiment-edit-conclusion-comment"
                        />
                        <SheetError message={error} testID="experiment-edit-conclusion-error" />
                    </Animated.ScrollView>
                </GestureDetector>
                <SheetFooter
                    reason={conclusion || pending ? null : 'Select a conclusion'}
                    pending={pending}
                    onCancel={onClose}
                    primary={{
                        label: pending ? 'Saving…' : 'Save',
                        onPress: save,
                        tone: 'ink',
                        testID: 'experiment-edit-conclusion-save',
                    }}
                />
            </View>
        </BottomSheet>
    )
}

const useStyles = createStyles(() => ({
    content: {
        flexShrink: 1,
        minHeight: 0,
    },
    scroll: {
        flexGrow: 0,
        flexShrink: 1,
    },
}))
