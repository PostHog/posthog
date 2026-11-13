import { useActions } from 'kea'
import { useEffect, useMemo } from 'react'

import { RichContentMention } from 'lib/components/RichContentEditor/RichContentMention'
import { RichContentRoleMention } from 'lib/components/RichContentEditor/RichContentRoleMention'

import { membersLogic } from '~/models/membersLogic'

import { splitNoteMentions } from '../../utils/reportNotes'

/** Note text as written, with each `@member:` and `@role:` token shown as the chip the Notes list shows. */
export function NoteMentionText({ text }: { text: string }): JSX.Element {
    const segments = useMemo(() => splitNoteMentions(text), [text])
    const { ensureAllMembersLoaded } = useActions(membersLogic)
    const hasMemberMention = segments.some((segment) => segment.kind === 'member')

    useEffect(() => {
        if (hasMemberMention) {
            ensureAllMembersLoaded()
        }
    }, [hasMemberMention, ensureAllMembersLoaded])

    return (
        <>
            {segments.map((segment, index) =>
                segment.kind === 'member' ? (
                    <RichContentMention key={index} id={segment.id} />
                ) : segment.kind === 'role' ? (
                    <RichContentRoleMention key={index} id={segment.id} />
                ) : (
                    <span key={index}>{segment.text}</span>
                )
            )}
        </>
    )
}
