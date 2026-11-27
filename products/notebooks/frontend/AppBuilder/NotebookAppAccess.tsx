import { useValues } from 'kea'
import posthog from 'posthog-js'
import { lazy, Suspense, useState } from 'react'

import { LemonButton, LemonInput, LemonModal } from '@posthog/lemon-ui'

import { OrganizationMembershipLevel } from 'lib/constants'
import { LemonLabel } from 'lib/lemon-ui/LemonLabel'
import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { notebooksAppViewGrantsActiveList, notebooksAppViewGrantsCreate } from '../generated/api'
import type { ActiveAppViewGrantApi } from '../generated/api.schemas'

interface NotebookAppAccessProps {
    project: string
    shortId: string
    revision: number
}

export function NotebookAppAccess(props: NotebookAppAccessProps): JSX.Element | null {
    const { user } = useValues(userLogic)
    if (!user || (user.organization?.membership_level ?? 0) < OrganizationMembershipLevel.Admin) {
        return null
    }

    return (
        <NotebookAppAccessControls
            key={[user.uuid, props.project, props.shortId, props.revision].join(':')}
            {...props}
        />
    )
}

function NotebookAppAccessControls({ project, shortId, revision }: NotebookAppAccessProps): JSX.Element {
    const [open, setOpen] = useState(false)
    const [email, setEmail] = useState('')
    const [busy, setBusy] = useState(false)
    const [link, setLink] = useState('')
    const [message, setMessage] = useState('')
    const [grants, setGrants] = useState<ActiveAppViewGrantApi[]>([])
    const [hasMore, setHasMore] = useState(false)
    const [listError, setListError] = useState(false)

    async function loadGrants(offset = 0): Promise<void> {
        setListError(false)
        try {
            const result = await notebooksAppViewGrantsActiveList(project, shortId, { limit: 10, offset })
            setGrants((current) => (offset ? [...current, ...result.results] : result.results))
            setHasMore(!!result.next)
        } catch {
            setListError(true)
        }
    }

    async function showGrants(offset = 0): Promise<void> {
        setBusy(true)
        await loadGrants(offset)
        setBusy(false)
    }

    async function submit(revoke: boolean, recipientUuid?: string): Promise<void> {
        setBusy(true)
        setMessage('')
        setLink('')
        try {
            const result = await notebooksAppViewGrantsCreate(project, shortId, {
                ...(recipientUuid ? { recipient_uuid: recipientUuid } : { email: email.trim() }),
                revoke,
                revision,
            })
            if (result.url) {
                setLink(urls.absolute(result.url))
            }
            setMessage(revoke ? 'App-only access removed.' : 'Send this link to the recipient.')
            await loadGrants()
            posthog.capture(revoke ? 'notebook app access revoked' : 'notebook app access granted', {
                short_id: shortId,
            })
        } catch {
            setMessage(
                revoke
                    ? 'Could not remove access. Check the active recipients and try again.'
                    : 'Could not grant access. Check the member and the published revision, then try again.'
            )
        } finally {
            setBusy(false)
        }
    }

    return (
        <>
            <LemonButton
                size="small"
                onClick={() => {
                    setOpen(true)
                    void showGrants()
                }}
            >
                App-only access
            </LemonButton>
            <LemonModal
                isOpen={open}
                onClose={() => {
                    if (busy) {
                        return
                    }
                    setOpen(false)
                    setLink('')
                    setEmail('')
                    setMessage('')
                    setGrants([])
                    setHasMore(false)
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
                <h3 className="mt-4">Active recipients</h3>
                {grants.map((grant) => (
                    <div key={grant.recipient_uuid + ':' + grant.revision} className="flex items-center gap-2">
                        <span className="flex-1">
                            {grant.email} · Release {grant.revision}
                        </span>
                        <LemonButton
                            size="small"
                            status="danger"
                            disabled={busy}
                            onClick={() => void submit(true, grant.recipient_uuid)}
                        >
                            Remove access
                        </LemonButton>
                    </div>
                ))}
                {listError ? (
                    <LemonButton disabled={busy} onClick={() => void showGrants()}>
                        Retry loading recipients
                    </LemonButton>
                ) : hasMore ? (
                    <LemonButton disabled={busy} onClick={() => void showGrants(grants.length)}>
                        Show more
                    </LemonButton>
                ) : !busy && grants.length === 0 ? (
                    <p>No active recipients.</p>
                ) : null}
            </LemonModal>
            <Suspense fallback={null}>
                <NotebookAppEmbed project={project} shortId={shortId} revision={revision} />
            </Suspense>
        </>
    )
}

const NotebookAppEmbed = lazy(async () => ({ default: (await import('./NotebookAppEmbed')).NotebookAppEmbed }))
