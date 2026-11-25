import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LemonTable, type LemonTableProps } from 'lib/lemon-ui/LemonTable'

import { QuillAiVisibilityTable } from './QuillAiVisibilityTable'

/** A table in AI visibility: quill under the new navigation, a Lemon table otherwise. Both take the Lemon table's props. */
export function AiVisibilityTable<T extends Record<string, any>>(props: LemonTableProps<T>): JSX.Element {
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    return todayRailNav ? <QuillAiVisibilityTable<T> {...props} /> : <LemonTable<T> {...props} />
}
