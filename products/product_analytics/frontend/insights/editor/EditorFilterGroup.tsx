import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

import type { InsightEditorFilterGroup, InsightLogicProps } from '~/types'

import { EditorFilterGroupTile } from './EditorFilterGroupTile'
import { QuillEditorFilterGroupTile } from './QuillEditorFilterGroupTile'

export interface EditorFilterGroupProps {
    editorFilterGroup: InsightEditorFilterGroup
    insightProps: InsightLogicProps
    queryKind?: string
}

export function EditorFilterGroup({ insightProps, editorFilterGroup, queryKind }: EditorFilterGroupProps): JSX.Element {
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    return todayRailNav ? (
        <QuillEditorFilterGroupTile
            insightProps={insightProps}
            editorFilterGroup={editorFilterGroup}
            queryKind={queryKind}
        />
    ) : (
        <EditorFilterGroupTile
            insightProps={insightProps}
            editorFilterGroup={editorFilterGroup}
            queryKind={queryKind}
        />
    )
}
