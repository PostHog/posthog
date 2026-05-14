import { LemonSelect, LemonTextArea } from '@posthog/lemon-ui'

import api from 'lib/api'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'

import { Incident, IncidentUpdateKeyword } from './uptimeSceneLogic'

const KEYWORD_OPTIONS: { label: string; value: IncidentUpdateKeyword }[] = [
    { label: 'Investigating', value: 'investigating' },
    { label: 'Identified', value: 'identified' },
    { label: 'Fixing', value: 'fixing' },
    { label: 'Monitoring fix', value: 'monitoring' },
    { label: 'Resolved', value: 'resolved' },
    { label: 'Update', value: 'update' },
]

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

export function openPostIncidentUpdateDialog({
    incident,
    projectId,
    onPosted,
}: {
    incident: Incident
    projectId: string
    onPosted: () => void
}): void {
    // If the incident is already resolved, default to a freeform "update" so the keyword
    // doesn't immediately reopen the incident under the user. Otherwise default to the
    // most common starting keyword.
    const defaultKeyword: IncidentUpdateKeyword = incident.resolved_at ? 'update' : 'investigating'
    LemonDialog.openForm({
        title: `Post update on "${incident.name}"`,
        description:
            'Pick a keyword and write a short note. Updates are appended to the incident timeline, newest first.',
        initialValues: { keyword: defaultKeyword, message: '' },
        content: (
            <div className="flex flex-col gap-3">
                <LemonField name="keyword" label="Keyword">
                    <LemonSelect<IncidentUpdateKeyword> options={KEYWORD_OPTIONS} fullWidth />
                </LemonField>
                <LemonField name="message" label="What's going on?">
                    <LemonTextArea
                        autoFocus
                        placeholder="e.g. Restarted the worker pool — error rate is dropping."
                        rows={4}
                    />
                </LemonField>
            </div>
        ),
        errors: {
            message: (msg: string) => (!msg?.trim() ? 'Write something to post' : undefined),
        },
        primaryButtonProps: { children: 'Post update' },
        shouldAwaitSubmit: true,
        onSubmit: async ({ keyword, message }) => {
            await api.create<Incident>(`api/projects/${projectId}/uptime/incidents/${incident.id}/post_update/`, {
                keyword,
                message: message.trim(),
            })
            lemonToast.success('Update posted')
            onPosted()
        },
    })
}
