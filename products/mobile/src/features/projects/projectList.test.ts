import type { AuthProject } from '@/auth/authStore'

import { filterProjects, groupByOrganization, orderSettingsProjects } from './projectList'

const web: AuthProject = { id: 1, name: 'Web app', organizationId: 'org-a', organizationName: 'Example Co' }
const api: AuthProject = { id: 2, name: 'Public API', organizationId: 'org-a', organizationName: 'Example Co' }
const docs: AuthProject = { id: 3, name: 'Docs site', organizationId: 'org-b', organizationName: 'Sample Labs' }
const projects = [web, api, docs]

describe('projectList', () => {
    test.each<[string, string, AuthProject[]]>([
        ['an empty query returns every project', '', projects],
        ['a whitespace query returns every project', '   ', projects],
        ['matches by project name', 'api', [api]],
        ['ignores the organization name', 'sample', []],
        ['ignores case and surrounding spaces', '  WEB ', [web]],
        ['returns nothing when no project matches', 'mobile', []],
    ])('filterProjects: %s', (_name, query, expected) => {
        expect(filterProjects(projects, query)).toEqual(expected)
    })

    test('groupByOrganization keeps store order and starts a group at each organization change', () => {
        expect(groupByOrganization(projects)).toEqual([
            { id: 'org-a', name: 'Example Co', projects: [web, api] },
            { id: 'org-b', name: 'Sample Labs', projects: [docs] },
        ])
    })

    test.each<[number | null, AuthProject[]]>([
        [web.id, [web, api, docs]],
        [docs.id, [docs, api, web]],
        [null, [api, web, docs]],
        [999, [api, web, docs]],
    ])('settings orders projects for selection %s without changing store order', (projectId, expected) => {
        expect(orderSettingsProjects(projects, projectId)).toEqual(expected)
        expect(projects).toEqual([web, api, docs])
    })
})
