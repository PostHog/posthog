import { useActions, useValues } from 'kea'

import { IconTrash } from '@posthog/icons'
import {
    LemonButton,
    LemonDialog,
    LemonInput,
    LemonModal,
    LemonTable,
    LemonTableColumns,
    LemonTag,
    LemonTextArea,
    Link,
} from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { ErrorTrackingSigningKey } from 'lib/components/Errors/types'

import { signingKeysLogic } from './signingKeysLogic'

export function SigningKeys(): JSX.Element {
    const { signingKeys, signingKeysLoading, modalOpen, label, publicKey } = useValues(signingKeysLogic)
    const { setModalOpen, setLabel, setPublicKey, createSigningKey, revokeSigningKey } = useActions(signingKeysLogic)

    const columns: LemonTableColumns<ErrorTrackingSigningKey> = [
        {
            title: 'Key ID',
            dataIndex: 'key_id',
            render: (key_id) => <span className="font-mono">{key_id as string}</span>,
        },
        { title: 'Label', dataIndex: 'label', render: (l) => (l as string) || <i className="text-muted">—</i> },
        {
            title: 'Status',
            dataIndex: 'revoked',
            render: (revoked) =>
                revoked ? <LemonTag type="danger">Revoked</LemonTag> : <LemonTag type="success">Active</LemonTag>,
        },
        { title: 'Added', dataIndex: 'created_at', render: (t) => <TZLabel time={t as string} /> },
        {
            title: 'Last used',
            dataIndex: 'last_used_at',
            render: (t) => (t ? <TZLabel time={t as string} /> : <span className="text-muted">never</span>),
        },
        {
            title: '',
            align: 'right',
            render: (_, key) =>
                key.revoked ? null : (
                    <LemonButton
                        type="tertiary"
                        size="xsmall"
                        status="danger"
                        icon={<IconTrash />}
                        tooltip="Revoke"
                        onClick={() =>
                            LemonDialog.open({
                                title: 'Revoke signing key?',
                                description:
                                    'Exceptions signed with this key will stop being verified. Existing tasks are unaffected. This cannot be undone.',
                                primaryButton: {
                                    type: 'primary',
                                    status: 'danger',
                                    children: 'Revoke',
                                    onClick: () => revokeSigningKey(key.id),
                                },
                                secondaryButton: { children: 'Cancel' },
                            })
                        }
                    />
                ),
        },
    ]

    return (
        <div className="deprecated-space-y-4">
            <p>
                Register the <strong>public</strong> half of an Ed25519 key your backend signs exceptions with (via a
                backend SDK's exception signing). PostHog verifies signed <code>$exception</code> events against these
                keys and marks them <code>$exception_verified</code>, so you can prove an exception genuinely came from
                your backend rather than being forged through the public ingest key. Keep the private key in your
                backend only. <Link to="https://posthog.com/docs/error-tracking">Learn more</Link>.
            </p>

            <div className="flex justify-end">
                <LemonButton type="primary" onClick={() => setModalOpen(true)}>
                    Add signing key
                </LemonButton>
            </div>

            <LemonTable
                id="error-tracking-signing-keys"
                columns={columns}
                dataSource={signingKeys}
                loading={signingKeysLoading}
                emptyState="No signing keys registered yet."
                rowKey="id"
            />

            <LemonModal
                isOpen={modalOpen}
                onClose={() => setModalOpen(false)}
                title="Add signing key"
                description="Paste the PEM-encoded Ed25519 public key. The matching key ID is derived automatically."
                footer={
                    <>
                        <LemonButton type="secondary" onClick={() => setModalOpen(false)}>
                            Cancel
                        </LemonButton>
                        <LemonButton
                            type="primary"
                            disabledReason={!publicKey.trim() ? 'Paste a public key' : undefined}
                            onClick={() => createSigningKey()}
                        >
                            Add key
                        </LemonButton>
                    </>
                }
            >
                <div className="deprecated-space-y-2">
                    <LemonInput
                        placeholder="Label (optional) — e.g. production backend"
                        value={label}
                        onChange={setLabel}
                    />
                    <LemonTextArea
                        placeholder={'-----BEGIN PUBLIC KEY-----\n...\n-----END PUBLIC KEY-----'}
                        value={publicKey}
                        onChange={setPublicKey}
                        minRows={5}
                        className="font-mono"
                    />
                </div>
            </LemonModal>
        </div>
    )
}
