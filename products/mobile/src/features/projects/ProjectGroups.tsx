import type { ReactElement } from 'react'
import { Text } from 'react-native'

import type { AuthProject } from '@/auth/authStore'
import { createStyles } from '@/ui/theme'
import { type } from '@/ui/tokens'

import type { OrganizationProjects } from './projectList'

interface ProjectGroupsProps {
    groups: OrganizationProjects[]
    showOrganizations: boolean
    children: (project: AuthProject) => ReactElement
}

/** The Project card's rows, under an organization label when the account has more than one organization. */
export function ProjectGroups({ groups, showOrganizations, children }: ProjectGroupsProps): ReactElement {
    const styles = useStyles()
    return (
        <>
            {groups.flatMap((group) => [
                ...(showOrganizations
                    ? [
                          <Text key={`org-${group.id}`} style={[type.eyebrow, styles.organization]} numberOfLines={1}>
                              {group.name.toUpperCase()}
                          </Text>,
                      ]
                    : []),
                ...group.projects.map(children),
            ])}
        </>
    )
}

const useStyles = createStyles(({ colors }) => ({
    organization: {
        color: colors.tertiary,
        paddingHorizontal: 4,
        paddingTop: 14,
        paddingBottom: 4,
    },
}))
