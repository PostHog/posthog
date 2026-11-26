import { useActions } from 'kea'
import { useEffect, useMemo } from 'react'

import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'

import { membersLogic } from '~/models/membersLogic'

import { splitNoteMentions } from '../../utils/reportNotes'

/** Note text as Markdown, with each `@member:` and `@role:` token shown as the chip the Notes list shows. */
export function NoteMentionText({ text }: { text: string }): JSX.Element {
    const hasMemberMention = useMemo(() => splitNoteMentions(text).some((segment) => segment.kind === 'member'), [text])
    const { ensureAllMembersLoaded } = useActions(membersLogic)

    useEffect(() => {
        if (hasMemberMention) {
            ensureAllMembersLoaded()
        }
    }, [hasMemberMention, ensureAllMembersLoaded])

    return <LemonMarkdown disableImages>{text}</LemonMarkdown>
}
