import { useActions, useValues } from 'kea'

import { LemonSelect } from '@posthog/lemon-ui'

import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'

import { membersLogic } from '~/models/membersLogic'

/** Test recipients for a sandbox email step: the sandbox sender only delivers to verified members. */
export function SandboxTestRecipientSelect({
    value,
    onChange,
}: {
    value: string
    onChange: (email: string) => void
}): JSX.Element {
    const { meFirstMembers, membersLoading } = useValues(membersLogic)
    const { ensureAllMembersLoaded } = useActions(membersLogic)

    useOnMountEffect(ensureAllMembersLoaded)

    const options = meFirstMembers
        .filter((member) => member.user.is_email_verified)
        .map((member) => ({
            value: member.user.email,
            label: member.user.first_name ? `${member.user.first_name} (${member.user.email})` : member.user.email,
        }))

    return (
        <LemonSelect
            fullWidth
            className="mt-1"
            value={options.some((option) => option.value === value) ? value : null}
            onChange={(email) => email && onChange(email)}
            options={options}
            loading={membersLoading}
            placeholder="Choose a verified member"
            data-attr="workflow-sandbox-test-recipient"
        />
    )
}
