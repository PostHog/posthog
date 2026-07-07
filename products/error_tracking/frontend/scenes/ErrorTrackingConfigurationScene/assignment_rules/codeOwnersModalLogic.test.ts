import { expectLogic } from 'kea-test-utils'

import { lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'

import { resumeKeaLoadersErrors, silenceKeaLoadersErrors } from '~/initKea'
import { initKeaTests } from '~/test/init'
import { RoleType } from '~/types'

import { rulesLogic } from '../rules/rulesLogic'
import { ErrorTrackingRuleType } from '../rules/types'
import { codeOwnersModalLogic } from './codeOwnersModalLogic'

function role(id: string, name: string): RoleType {
    return { id, name } as RoleType
}

describe('codeOwnersModalLogic', () => {
    let logic: ReturnType<typeof codeOwnersModalLogic.build>
    let assignmentRulesLogic: ReturnType<typeof rulesLogic.build>
    let createRuleSpy: jest.SpyInstance
    let loadRulesSpy: jest.SpyInstance

    beforeEach(() => {
        initKeaTests()
        jest.spyOn(api.roles, 'list').mockResolvedValue({ results: [role('error-tracking', 'Error tracking')] } as any)
        jest.spyOn(api.organizationMembers, 'listAll').mockResolvedValue([] as any)
        jest.spyOn(api, 'query').mockResolvedValue({ results: [[3, 2]] } as any)
        loadRulesSpy = jest.spyOn(api.errorTracking, 'rules').mockResolvedValue({ results: [] } as any)
        createRuleSpy = jest.spyOn(api.errorTracking, 'createRule').mockResolvedValue({ id: 'new-rule' } as any)
        jest.spyOn(lemonToast, 'warning').mockImplementation(jest.fn())
        jest.spyOn(lemonToast, 'error').mockImplementation(jest.fn())

        assignmentRulesLogic = rulesLogic({ ruleType: ErrorTrackingRuleType.Assignment })
        assignmentRulesLogic.mount()
        logic = codeOwnersModalLogic()
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
        assignmentRulesLogic.unmount()
        resumeKeaLoadersErrors()
        jest.restoreAllMocks()
    })

    it('derives parsed owners and concise parse errors from raw text', async () => {
        await expectLogic(logic, () => {
            logic.actions.setRawText(['frontend/** @posthog/frontend', 'backend/**'].join('\n'))
        }).toMatchValues({
            parsedOwners: [{ owner: '@posthog/frontend', patterns: ['frontend/**'], index: 0 }],
            parseErrors: [{ line: 2, reason: 'Missing owner' }],
            hasParsedOwners: true,
        })
    })

    it('loads assignable roles and users when opened and resets modal state', async () => {
        await expectLogic(logic, () => {
            logic.actions.setRawText('frontend/** @posthog/frontend')
            logic.actions.setOwnerAssignee('@posthog/frontend', { type: 'role', id: 'frontend' })
            logic.actions.openModal()
        })
            .toFinishAllListeners()
            .toMatchValues({
                isOpen: true,
                step: 'paste',
                rawText: '',
                assigneeOverrides: {},
                matchResults: {},
            })

        expect(api.roles.list).toHaveBeenCalled()
        expect(api.organizationMembers.listAll).toHaveBeenCalled()
    })

    it('freezes owners to map when entering the mapping step', async () => {
        await expectLogic(logic, () => {
            logic.actions.setRawText('a/** @team/backend\nb/** @team/backend\nc/** @team/frontend')
            logic.actions.goToConfigure()
        })
            .toFinishAllListeners()
            .toMatchValues({
                step: 'configure',
                ownersToMap: ['@team/backend', '@team/backend', '@team/frontend'],
                mappingRows: expect.arrayContaining([
                    expect.objectContaining({ owner: '@team/backend', patterns: ['a/**', 'b/**'] }),
                    expect.objectContaining({ owner: '@team/frontend', patterns: ['c/**'] }),
                ]),
            })
    })

    it('keeps manual assignee picks over automatic matches', async () => {
        await expectLogic(logic, () => {
            logic.actions.setRawText('a/** @posthog/error-tracking')
            logic.actions.setOwnerAssignee('@posthog/error-tracking', { type: 'user', id: 123 })
        }).toMatchValues({
            ownerRows: [
                expect.objectContaining({
                    owner: '@posthog/error-tracking',
                    assignee: { type: 'user', id: 123 },
                }),
            ],
        })
    })

    it('retests impact when the date range changes on the impact step', async () => {
        await expectLogic(logic, () => {
            logic.actions.setRawText('a/** @team/backend')
            logic.actions.setOwnerAssignee('@team/backend', { type: 'role', id: 'backend' })
            logic.actions.goToImpact()
        }).toFinishAllListeners()

        jest.mocked(api.query).mockClear()

        await expectLogic(logic, () => {
            logic.actions.setDateRange('-30d')
        }).toFinishAllListeners()

        expect(api.query).toHaveBeenCalledWith(expect.objectContaining({ after: '-30d' }))
    })

    it('saves all generated assignment rules and reloads rules on success', async () => {
        await expectLogic(logic, () => {
            logic.actions.openModal()
            logic.actions.setRawText('a/** @team/backend')
            logic.actions.setOwnerAssignee('@team/backend', { type: 'role', id: 'backend' })
            logic.actions.saveAll()
        })
            .toFinishAllListeners()
            .toMatchValues({ isOpen: false, savingLoading: false })

        expect(createRuleSpy).toHaveBeenCalledWith(
            ErrorTrackingRuleType.Assignment,
            expect.objectContaining({ assignee: { type: 'role', id: 'backend' } })
        )
        expect(loadRulesSpy).toHaveBeenCalledWith(ErrorTrackingRuleType.Assignment)
    })

    it('reports partial save failures while keeping successful creates', async () => {
        createRuleSpy.mockReset()
        createRuleSpy.mockResolvedValueOnce({ id: 'created' } as any).mockRejectedValueOnce(new Error('nope'))

        await expectLogic(logic, () => {
            logic.actions.openModal()
            logic.actions.setRawText('a/** @team/backend\nb/** @team/frontend')
            logic.actions.setOwnerAssignee('@team/backend', { type: 'role', id: 'backend' })
            logic.actions.setOwnerAssignee('@team/frontend', { type: 'role', id: 'frontend' })
            logic.actions.saveAll()
        })
            .toFinishAllListeners()
            .toMatchValues({ isOpen: false, savingLoading: false })

        expect(createRuleSpy).toHaveBeenCalledTimes(2)
        expect(loadRulesSpy).toHaveBeenCalledWith(ErrorTrackingRuleType.Assignment)
        expect(lemonToast.warning).toHaveBeenCalledWith('Created 1 of 2 assignment rules. 1 failed.')
        expect(lemonToast.error).not.toHaveBeenCalled()
    })

    it('reloads rules and shows an error when every create fails', async () => {
        silenceKeaLoadersErrors()
        createRuleSpy.mockReset()
        createRuleSpy.mockRejectedValue(new Error('nope'))

        await expectLogic(logic, () => {
            logic.actions.setRawText('a/** @team/backend')
            logic.actions.setOwnerAssignee('@team/backend', { type: 'role', id: 'backend' })
            logic.actions.saveAll()
        })
            .toFinishAllListeners()
            .toMatchValues({ savingLoading: false })

        expect(loadRulesSpy).toHaveBeenCalledWith(ErrorTrackingRuleType.Assignment)
        expect(lemonToast.error).toHaveBeenCalledWith('Failed to save assignment rules')
    })
})
