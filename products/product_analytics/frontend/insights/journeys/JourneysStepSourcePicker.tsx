import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

import { EditorFilterProps } from '~/types'

import { LemonJourneysStepSourcePicker } from './LemonJourneysStepSourcePicker'
import { QuillJourneysStepSourcePicker } from './QuillJourneysStepSourcePicker'

export function JourneysStepSourcePicker(props: EditorFilterProps): JSX.Element {
    const quillEnabled = useFeatureFlag('TODAY_RAIL_NAV')
    return quillEnabled ? <QuillJourneysStepSourcePicker {...props} /> : <LemonJourneysStepSourcePicker {...props} />
}
