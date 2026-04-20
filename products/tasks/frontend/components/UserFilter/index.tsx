import { useActions, useValues } from 'kea'

import { LemonButton } from '@posthog/lemon-ui'

import { taskTrackerSceneLogic } from '../../logics/taskTrackerSceneLogic'
import { UserDisplay, UserSelect } from './UserSelect'

export const UserFilter = (): JSX.Element => {
    const { createdBy } = useValues(taskTrackerSceneLogic)
    const { setCreatedBy } = useActions(taskTrackerSceneLogic)

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
