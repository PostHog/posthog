import { useActions, useValues } from 'kea'

import { LemonButton } from '@posthog/lemon-ui'

import { tasksLogic } from '../../tasksLogic'
import { UserDisplay, UserSelect } from './UserSelect'

export const UserFilter = (): JSX.Element => {
    const { createdBy } = useValues(tasksLogic)
    const { setCreatedBy } = useActions(tasksLogic)

    return (
        <UserSelect userId={createdBy} onChange={setCreatedBy}>
            {(user) => (
                <LemonButton type="secondary" size="small">
                    <UserDisplay user={user} />
                </LemonButton>
            )}
        </UserSelect>
    )
}
