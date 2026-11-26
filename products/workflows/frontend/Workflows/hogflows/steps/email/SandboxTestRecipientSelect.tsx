import { useActions } from 'kea'

import { LemonSelect } from '@posthog/lemon-ui'

import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'

import { membersLogic } from '~/models/membersLogic'
import { OrganizationMemberType } from '~/types'

export function SandboxTestRecipientSelect({
    members,
    loading,
    value,
    onChange,
}: {
    members: OrganizationMemberType[]
    loading: boolean
    value: string | null
    onChange: (email: string) => void
}): JSX.Element {
    const { ensureAllMembersLoaded } = useActions(membersLogic)

    useOnMountEffect(ensureAllMembersLoaded)

    return (
        <LemonSelect
            fullWidth
            className="mt-1"
            value={value}
            onChange={(email) => email && onChange(email)}
            options={members.map(({ user }) => ({
                value: user.email,
                label: user.first_name ? `${user.first_name} (${user.email})` : user.email,
            }))}
            loading={loading}
            placeholder="Choose a verified member"
            data-attr="workflow-sandbox-test-recipient"
        />
    )
}
