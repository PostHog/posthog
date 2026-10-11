import { useActions } from 'kea'

import type { InsightLogicProps } from '~/types'

import { EditableWord } from '../sentence/EditableWord'
import { insightFollowUpsLogic } from './insightFollowUpsLogic'
import type { FollowUpSlot } from './insightFollowUpsLogic'

export function SentenceFollowUpWord({
    insightProps,
    slot,
    itemId,
    label,
}: {
    insightProps: InsightLogicProps
    slot: FollowUpSlot
    itemId: string | null
    label: string
}): JSX.Element {
    const { openFollowUp } = useActions(insightFollowUpsLogic(insightProps))

    return (
        <EditableWord
            color="yellow"
            onClick={() => openFollowUp(slot, itemId)}
            data-attr={`quill-insight-sentence-${slot}`}
        >
            {label}
        </EditableWord>
    )
}
