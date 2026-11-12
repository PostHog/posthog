import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'

import { ScoutNoteAudience } from './ScoutNoteAudience'

/**
 * A note a person left, as it reads in Activity. The Notes list under the report shows the note itself
 * with its controls, so here it is a quote: the record of what was said and when.
 */
export function ActivityNoteQuote({
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
        <div className="w-full">
            {scoutSkillName !== undefined && (
                <span className="mb-1 block text-xs text-tertiary">
                    <ScoutNoteAudience reportId={reportId} skillName={scoutSkillName} />
                </span>
            )}
            <blockquote className="m-0 border-l-2 border-primary pl-2 text-xs italic text-secondary">
                <LemonMarkdown disableImages>{text}</LemonMarkdown>
            </blockquote>
        </div>
    )
}
