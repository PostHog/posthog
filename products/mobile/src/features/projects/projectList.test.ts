import type { AuthProject } from '@/auth/authStore'
import { EU_ACCOUNT, SELF_HOSTED_ACCOUNT, US_ACCOUNT } from '@/features/accounts/testAccounts'

import { accountSections, filterProjects, groupByOrganization, orderSettingsProjects } from './projectList'

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

    test.each<[string, string, string[], string[], number]>([
        [
            'lists the active account first, then the others in the order they were added',
            '',
            [`${EU_ACCOUNT.key}:projects`, `${US_ACCOUNT.key}:projects`, `${SELF_HOSTED_ACCOUNT.key}:needs_sign_in`],
            [],
            4,
        ],
        [
            'searches every account and keeps only accounts with a match',
            'web',
            [`${EU_ACCOUNT.key}:projects`, `${US_ACCOUNT.key}:projects`],
            [SELF_HOSTED_ACCOUNT.key],
            3,
        ],
        [
            'skips an account that needs a sign-in, even when its saved projects match',
            'internal',
            [],
            [SELF_HOSTED_ACCOUNT.key],
            0,
        ],
    ])('accountSections %s', (_name, query, sections, skipped, matches) => {
        const list = accountSections([US_ACCOUNT, SELF_HOSTED_ACCOUNT, EU_ACCOUNT], EU_ACCOUNT.key, query)
        expect(list.sections.map((section) => `${section.account.key}:${section.state}`)).toEqual(sections)
        expect(list.skipped.map((section) => section.account.key)).toEqual(skipped)
        expect(list.matches).toBe(matches)
    })

    test('accountSections keeps organization labels for an account with several organizations while a search matches one', () => {
        const [us] = accountSections([US_ACCOUNT, EU_ACCOUNT], US_ACCOUNT.key, 'hedgebox').sections
        expect(us?.showOrganizations).toBe(true)
        expect(us?.groups.map((group) => group.name)).toEqual(['Hedgebox'])
    })

    test('accountSections shows an inactive account without loaded details as one to switch to', () => {
        const { sections } = accountSections([US_ACCOUNT, { ...EU_ACCOUNT, user: null }], US_ACCOUNT.key, '')
        expect(sections.map((section) => section.state)).toEqual(['projects', 'not_loaded'])
    })
})
