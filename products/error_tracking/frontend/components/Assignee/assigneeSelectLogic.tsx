import Fuse from 'fuse.js'
import { actions, connect, kea, listeners, path, props, reducers, selectors } from 'kea'

import { membersLogic } from 'scenes/organization/membersLogic'
import { rolesLogic } from 'scenes/settings/organization/Permissions/Roles/rolesLogic'

import { ErrorTrackingIssue } from '~/queries/schema/schema-general'
import type { OrganizationMemberType, RoleType } from '~/types'

import type { assigneeSelectLogicType } from './assigneeSelectLogicType'

export type ErrorTrackingAssigneeSelectProps = {
    assignee: ErrorTrackingIssue['assignee']
}

export type UserAssignee = {
    id: number
    type: 'user'
    user: OrganizationMemberType['user']
}

export type RoleAssignee = {
    id: string
    type: 'role'
    role: RoleType
}

export type Assignee = UserAssignee | RoleAssignee | null

export interface RolesFuse extends Fuse<RoleType> {}

export const assigneeSelectLogic = kea<assigneeSelectLogicType>([
    path(['products', 'error_tracking', 'components', 'Assignee', 'assigneeSelectLogic']),
    props({} as ErrorTrackingAssigneeSelectProps),

    connect(() => ({
        values: [
            membersLogic,
            ['meFirstMembers', 'filteredMembers', 'membersLoading'],
            rolesLogic,
            ['roles', 'rolesLoading'],
        ],
        actions: [membersLogic, ['setSearch as setMembersSearch', 'ensureAllMembersLoaded']],
    })),

    actions({
        ensureAssigneeTypesLoaded: true,
        setSearch: (search) => ({ search }),
    }),

    reducers({
        search: ['', { setSearch: (_, { search }) => search }],
    }),

    listeners(({ values, actions }) => ({
        setSearch: () => {
            actions.setMembersSearch(values.search)
        },
        ensureAssigneeTypesLoaded: () => {
            actions.ensureAllMembersLoaded()
        },
    })),

    selectors({
        loading: [
            (s) => [s.membersLoading, s.rolesLoading],
            (membersLoading, rolesLoading): boolean => membersLoading || rolesLoading,
        ],

        rolesFuse: [
            (s) => [s.roles],
            (roles): RolesFuse => new Fuse<RoleType>(roles, { keys: ['name'], threshold: 0.3 }),
        ],
        filteredRoles: [
            (s) => [s.roles, s.rolesFuse, s.search],
            (roles, rolesFuse, search): RoleType[] =>
                search ? rolesFuse.search(search).map((result) => result.item) : (roles ?? []),
        ],

        resolveAssignee: [
            (s) => [s.roles, s.meFirstMembers],
            (roles, members): ((assignee: ErrorTrackingIssue['assignee']) => Assignee) => {
                return (assignee: ErrorTrackingIssue['assignee']) => {
                    if (assignee) {
                        if (assignee.type === 'role') {
                            const assignedRole = roles.find((role) => role.id === assignee.id)
                            return assignedRole
                                ? {
                                      id: assignedRole.id,
                                      type: 'role',
                                      role: assignedRole,
                                  }
                                : null
                        }

                        const assignedMember = members.find((member) => member.user.id === assignee.id)
                        return assignedMember
                            ? {
                                  id: assignedMember.user.id,
                                  type: 'user',
                                  user: assignedMember.user,
                              }
                            : null
                    }

                    return null
                }
            },
        ],
    }),
])
