import { actions, connect, kea, listeners, path, reducers, selectors } from 'kea'

import { membersLogic } from 'scenes/organization/membersLogic'

import type { OrganizationMemberType } from '~/types'

import type { userSelectLogicType } from './userSelectLogicType'

export type UserAssignee = {
    id: number
    user: OrganizationMemberType['user']
}

export const userSelectLogic = kea<userSelectLogicType>([
    path(['products', 'tasks', 'components', 'UserFilter', 'userSelectLogic']),

    connect(() => ({
        values: [membersLogic, ['meFirstMembers', 'filteredMembers', 'membersLoading']],
        actions: [membersLogic, ['setSearch as setMembersSearch', 'ensureAllMembersLoaded']],
    })),

    actions({
        ensureUsersLoaded: true,
        setSearch: (search) => ({ search }),
    }),

    reducers({
        search: ['', { setSearch: (_, { search }) => search }],
    }),

    listeners(({ values, actions }) => ({
        setSearch: () => {
            actions.setMembersSearch(values.search)
        },
        ensureUsersLoaded: () => {
            actions.ensureAllMembersLoaded()
        },
    })),

    selectors({
        users: [
            (s) => [s.meFirstMembers],
            (members): UserAssignee[] =>
                members.map((member) => ({
                    id: member.user.id,
                    user: member.user,
                })),
        ],
    }),
])
