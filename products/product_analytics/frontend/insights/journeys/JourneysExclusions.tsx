import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

import { EditorFilterProps } from '~/types'

import { LemonJourneysExclusions } from './LemonJourneysExclusions'
import { QuillJourneysExclusions } from './QuillJourneysExclusions'

export function JourneysExclusions(props: EditorFilterProps): JSX.Element {
    const quillEnabled = useFeatureFlag('TODAY_RAIL_NAV')
    return quillEnabled ? <QuillJourneysExclusions {...props} /> : <LemonJourneysExclusions {...props} />
}
