import { PLAYBOOK_CONTENT } from './playbookContent.generated'
// Embedded operator playbooks. Ids/titles come from playbookManifest.generated.ts
// and the markdown bodies from playbookContent.generated.ts — both regenerated
// from the concierge skills dir by scripts/copy-instructions.ts.
import { type PlaybookId, PLAYBOOK_IDS, PLAYBOOK_TITLES } from './playbookIds'

export interface Playbook {
    id: PlaybookId
    title: string
    content: string
}

export const PLAYBOOKS: Record<PlaybookId, Playbook> = Object.fromEntries(
    PLAYBOOK_IDS.map((id) => [id, { id, title: PLAYBOOK_TITLES[id], content: PLAYBOOK_CONTENT[id] }])
) as Record<PlaybookId, Playbook>
