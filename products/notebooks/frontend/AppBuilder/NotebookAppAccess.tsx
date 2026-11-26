import { useValues } from 'kea'
import posthog from 'posthog-js'
import { useState } from 'react'

import { LemonButton, LemonInput, LemonModal } from '@posthog/lemon-ui'

import { OrganizationMembershipLevel } from 'lib/constants'
import { LemonLabel } from 'lib/lemon-ui/LemonLabel'
import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { notebooksAppViewGrantsCreate } from '../generated/api'

export function NotebookAppAccess({ project, shortId }: { project: string; shortId: string }): JSX.Element | null {
    const { user } = useValues(userLogic)
    const [open, setOpen] = useState(false)
    const [email, setEmail] = useState('')
    const [busy, setBusy] = useState(false)
    const [link, setLink] = useState('')
    const [message, setMessage] = useState('')
    if ((user?.organization?.membership_level ?? 0) < OrganizationMembershipLevel.Admin) {
        return null
    }

    async function submit(revoke: boolean): Promise<void> {
        setBusy(true)
        setMessage('')
        setLink('')
        try {
            const result = await notebooksAppViewGrantsCreate(project, shortId, { email: email.trim(), revoke })
            if (result.url) {
                setLink(urls.absolute(result.url))
            }
            setMessage(revoke ? 'App-only access removed.' : 'Send this link to the recipient.')
            posthog.capture(revoke ? 'notebook app access revoked' : 'notebook app access granted', {
                short_id: shortId,
            })
        } catch {
            setMessage('Could not update access. Check that the email belongs to a project member and try again.')
        } finally {
            setBusy(false)
        }
    }

    return (
        <>
            <LemonButton size="small" onClick={() => setOpen(true)}>
                App-only access
            </LemonButton>
            <LemonModal
                isOpen={open}
                onClose={() => {
                    setOpen(false)
                    setLink('')
                    setEmail('')
                    setMessage('')
                }}
                title="App-only access"
            >
                <p>
                    Share the text and saved native SQL results from this release with a project member for up to 30
                    days. The recipient must sign in to open the link.
                </p>
                <LemonLabel htmlFor="notebook-app-recipient">Member email</LemonLabel>
                <LemonInput
                    type="email"
                    id="notebook-app-recipient"
                    value={email}
                    onChange={(value) => {
                        setEmail(value)
                        setLink('')
                        setMessage('')
                    }}
                    placeholder="member@example.com"
                    disabled={busy}
                    fullWidth
                />
                <div className="flex items-center gap-2 mt-3">
                    <LemonButton
                        type="primary"
                        loading={busy}
                        disabledReason={!email.trim() ? 'Enter a member email.' : undefined}
                        onClick={() => void submit(false)}
                    >
                        Create link
                    </LemonButton>
                    <LemonButton status="danger" disabled={!email.trim() || busy} onClick={() => void submit(true)}>
                        Remove access
                    </LemonButton>
                </div>
                {message && (
                    <p role="status" className="mt-3">
                        {message}
                    </p>
                )}
                {link && (
                    <div className="flex items-center gap-2">
                        <code className="flex-1 break-all">{link}</code>
                        <LemonButton type="secondary" onClick={() => void copyToClipboard(link, 'app-only link')}>
                            Copy link
                        </LemonButton>
                    </div>
                )}
            </LemonModal>
        </>
    )
}
