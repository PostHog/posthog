import { Text } from '@posthog/quill'

import { ScoutNoteAudience } from './ScoutNoteAudience'

/** The quill sibling of `ActivityNoteQuote`: a note a person left, quoted as the record of what was said. */
export function QuillActivityNoteQuote({
    reportId,
    text,
    scoutSkillName,
}: {
    reportId: string
    text: string
    /** Set for a note sent to the scouts. Blank means every scout. */
    scoutSkillName?: string
}): JSX.Element {
    return (
        <div className="flex w-full flex-col gap-1">
            {scoutSkillName !== undefined && (
                <Text size="xs" render={<span />} className="text-subtle-foreground">
                    <ScoutNoteAudience reportId={reportId} skillName={scoutSkillName} />
                </Text>
            )}
            <Text
                size="xs"
                render={<blockquote />}
                className="m-0 whitespace-pre-wrap border-s-2 border-border ps-2 italic text-muted-foreground"
            >
                {text}
            </Text>
        </div>
    )
}
