import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

import { EditorFilterProps } from '~/types'

import { LemonJourneysSettings } from './LemonJourneysSettings'
import { QuillJourneysSettings } from './QuillJourneysSettings'

export function JourneysSettings(props: EditorFilterProps): JSX.Element {
    const quillEnabled = useFeatureFlag('TODAY_RAIL_NAV')
    return quillEnabled ? <QuillJourneysSettings {...props} /> : <LemonJourneysSettings {...props} />
}
