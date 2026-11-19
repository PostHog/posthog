// PROTOTYPE (throwaway): drafts waiting to be finished, for overview B2.
import { Card, CardContent, CardHeader, CardTitle } from '@posthog/quill'

import { EntryBadges } from './EntryBadges'
import { DRAFTS } from './prototypeData'

export function DraftsList(): JSX.Element {
    return (
        <Card size="sm">
            <CardHeader>
                <CardTitle>Drafts</CardTitle>
            </CardHeader>
            <CardContent className="flex flex-col gap-2">
                {DRAFTS.map((draft) => (
                    <button
                        key={draft.id}
                        type="button"
                        className="flex flex-col gap-1 rounded-md px-1 py-1 text-left text-sm hover:bg-fill-hover"
                    >
                        <span className="font-medium">{draft.name}</span>
                        <span className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                            <EntryBadges kind={draft.kind} />
                            Edited {draft.edited} by {draft.by}
                        </span>
                    </button>
                ))}
            </CardContent>
        </Card>
    )
}
