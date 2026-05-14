import { LemonTextArea } from '@posthog/lemon-ui'

import api from 'lib/api'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'

import { Incident } from './uptimeSceneLogic'

export function openResolveIncidentDialog({
    incident,
    projectId,
    onResolved,
}: {
    incident: Incident
    projectId: string
    onResolved: () => void
}): void {
    LemonDialog.openForm({
        title: `Resolve declared incident "${incident.name}"`,
        description: 'Write a short note about what fixed it. The note is shown on the public status page.',
        initialValues: { resolution_note: incident.resolution_note ?? '' },
        content: (
            <LemonField name="resolution_note">
                <LemonTextArea autoFocus placeholder="e.g. Rolled back deploy abc123." rows={4} />
            </LemonField>
        ),
        errors: {
            resolution_note: (note: string) => (!note?.trim() ? 'A resolution note is required' : undefined),
        },
        primaryButtonProps: { children: 'Mark resolved' },
        shouldAwaitSubmit: true,
        onSubmit: async ({ resolution_note }) => {
            await api.create<Incident>(`api/projects/${projectId}/uptime/incidents/${incident.id}/resolve/`, {
                resolution_note: resolution_note.trim(),
            })
            lemonToast.success('Declared incident resolved')
            onResolved()
        },
    })
}
