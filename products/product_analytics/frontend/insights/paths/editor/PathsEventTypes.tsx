import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

import { EditorFilterProps } from '~/types'

import { LemonPathsEventsTypes } from './LemonPathsEventsTypes'
import { QuillPathsEventsTypes } from './QuillPathsEventsTypes'

export function PathsEventsTypes(props: EditorFilterProps): JSX.Element {
    const quillEnabled = useFeatureFlag('TODAY_RAIL_NAV')
    return quillEnabled ? <QuillPathsEventsTypes {...props} /> : <LemonPathsEventsTypes {...props} />
}
