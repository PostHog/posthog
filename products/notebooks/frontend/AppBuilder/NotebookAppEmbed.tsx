import posthog from 'posthog-js'
import { useState } from 'react'

import { LemonButton, LemonInput, LemonModal } from '@posthog/lemon-ui'

import { LemonLabel } from 'lib/lemon-ui/LemonLabel'
import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { urls } from 'scenes/urls'

import { notebooksAppEmbedsCreate } from '../generated/api'

export function NotebookAppEmbed({
    project,
    shortId,
    revision,
}: {
    project: string
    shortId: string
    revision: number
}): JSX.Element {
    const [open, setOpen] = useState(false)
    const [origin, setOrigin] = useState('')
    const [column, setColumn] = useState('')
    const [tenant, setTenant] = useState('')
    const [busy, setBusy] = useState(false)
    const [snippet, setSnippet] = useState('')
    const [message, setMessage] = useState('')

    async function issue(revoke: boolean): Promise<void> {
        setBusy(true)
        setSnippet('')
        setMessage('')
        try {
            const result = await notebooksAppEmbedsCreate(project, shortId, {
                origin,
                tenant_column: column.trim(),
                tenant_value: tenant,
                revoke,
                revision,
            })
            if (result.url) {
                const frame = document.createElement('iframe')
                frame.src = urls.absolute(result.url)
                frame.title = 'Published notebook app'
                frame.referrerPolicy = 'origin'
                frame.width = '100%'
                frame.height = '480'
                setSnippet(frame.outerHTML)
            }
            setMessage(
                revoke ? 'Embed revoked.' : 'Paste this embed code into the approved site. It expires in 24 hours.'
            )
            posthog.capture(revoke ? 'notebook app embed revoked' : 'notebook app embed created', { short_id: shortId })
        } catch {
            setMessage(
                'Could not update the embed. Check the site origin, the tenant column in each published result, and your organization’s public sharing settings.'
            )
        } finally {
            setBusy(false)
        }
    }

    function resetOutput(): void {
        setMessage('')
        setSnippet('')
    }

    const disabledReason =
        !origin || !column.trim() || !tenant ? 'Enter a site origin, tenant column, and tenant value.' : undefined
    return (
        <>
            <LemonButton size="small" onClick={() => setOpen(true)}>
                Signed embed
            </LemonButton>
            <LemonModal
                isOpen={open}
                onClose={() => {
                    if (busy) {
                        return
                    }
                    setOpen(false)
                    setOrigin('')
                    setColumn('')
                    setTenant('')
                    resetOutput()
                }}
                title="Signed embed"
            >
                <p>
                    Embed this release on one site. Each saved SQL result must have a string column identifying its
                    tenant. Only rows matching the tenant value are included. Published text is shared with every
                    tenant.
                </p>
                <div className="space-y-3">
                    <div>
                        <LemonLabel htmlFor="notebook-embed-origin">Site origin</LemonLabel>
                        <LemonInput
                            fullWidth
                            id="notebook-embed-origin"
                            value={origin}
                            placeholder="https://portal.example.com"
                            onChange={(v) => {
                                setOrigin(v)
                                resetOutput()
                            }}
                            disabled={busy}
                        />
                    </div>
                    <div>
                        <LemonLabel htmlFor="notebook-embed-column">Tenant column</LemonLabel>
                        <LemonInput
                            fullWidth
                            id="notebook-embed-column"
                            value={column}
                            placeholder="workspace_id"
                            onChange={(v) => {
                                setColumn(v)
                                resetOutput()
                            }}
                            disabled={busy}
                        />
                    </div>
                    <div>
                        <LemonLabel htmlFor="notebook-embed-tenant">Tenant value</LemonLabel>
                        <LemonInput
                            fullWidth
                            id="notebook-embed-tenant"
                            value={tenant}
                            onChange={(v) => {
                                setTenant(v)
                                resetOutput()
                            }}
                            disabled={busy}
                        />
                    </div>
                </div>
                <div className="flex items-center gap-2 mt-3">
                    <LemonButton
                        type="primary"
                        disabledReason={disabledReason}
                        loading={busy}
                        onClick={() => void issue(false)}
                    >
                        Create embed
                    </LemonButton>
                    <LemonButton
                        status="danger"
                        disabledReason={disabledReason}
                        disabled={busy}
                        onClick={() => void issue(true)}
                    >
                        Revoke embed
                    </LemonButton>
                </div>
                {message && (
                    <p role="status" className="mt-3">
                        {message}
                    </p>
                )}
                {snippet && (
                    <LemonButton type="secondary" onClick={() => void copyToClipboard(snippet, 'embed code')}>
                        Copy embed code
                    </LemonButton>
                )}
            </LemonModal>
        </>
    )
}
