import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import {
    workflowT3CodeMachinesRetrieve,
    workflowT3CodeProjectsCreate,
    workflowT3CodeWebhookTasksCreate,
} from '../../../../generated/api'
import type { T3CodeProjectsApi, T3CodeWebhookTaskApi } from '../../../../generated/api.schemas'
import { t3CodeTaskSetupLogic } from './t3CodeTaskSetupLogic'

jest.mock('../../../../generated/api', () => ({
    ...jest.requireActual('../../../../generated/api'),
    workflowT3CodeMachinesRetrieve: jest.fn(),
    workflowT3CodeProjectsCreate: jest.fn(),
    workflowT3CodeWebhookTasksCreate: jest.fn(),
}))

const machinesRetrieve = workflowT3CodeMachinesRetrieve as jest.Mock
const projectsCreate = workflowT3CodeProjectsCreate as jest.Mock
const webhookTasksCreate = workflowT3CodeWebhookTasksCreate as jest.Mock

interface Deferred<T> {
    promise: Promise<T>
    resolve: (value: T) => void
    reject: (error: Error) => void
}

function deferred<T>(): Deferred<T> {
    let resolve: (value: T) => void = () => {}
    let reject: (error: Error) => void = () => {}
    const promise = new Promise<T>((onResolve, onReject) => {
        resolve = onResolve
        reject = onReject
    })
    return { promise, resolve, reject }
}

function projectsOn(machine: string): T3CodeProjectsApi {
    return {
        status: 'ok',
        approval_token: null,
        projects: [{ id: `${machine}-project`, title: `${machine} project`, has_default_model: true }],
    }
}

describe('t3CodeTaskSetupLogic', () => {
    let onWebhookUrl: jest.Mock
    let logic: ReturnType<typeof t3CodeTaskSetupLogic.build>

    beforeEach(() => {
        initKeaTests()
        machinesRetrieve.mockResolvedValue({ machines: [] })
        projectsCreate.mockReset()
        webhookTasksCreate.mockReset()
        onWebhookUrl = jest.fn()
        logic = t3CodeTaskSetupLogic({ actionId: 'action-1', webhookUrl: null, onWebhookUrl })
        logic.mount()
    })

    it.each([
        ['answers', (reply: Deferred<T3CodeProjectsApi>) => reply.resolve(projectsOn('laptop'))],
        ['fails', (reply: Deferred<T3CodeProjectsApi>) => reply.reject(new Error('The laptop is offline'))],
    ])('ignores a machine the member switched away from when it %s late', async (_case, settleLaptop) => {
        const laptopProjects = deferred<T3CodeProjectsApi>()
        const devboxProjects = deferred<T3CodeProjectsApi>()
        projectsCreate.mockImplementation((_teamId: string, { machine }: { machine: string }) =>
            machine === 'laptop' ? laptopProjects.promise : devboxProjects.promise
        )

        logic.actions.setMachine('laptop')
        logic.actions.setMachine('devbox')
        devboxProjects.resolve(projectsOn('devbox'))
        settleLaptop(laptopProjects)

        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values).toMatchObject({ projects: projectsOn('devbox').projects, error: null })
    })

    it('appends the next page after the member allows it, keeping the projects already loaded', async () => {
        const later = { id: 'later-project', title: 'later project', has_default_model: true }
        projectsCreate.mockImplementation(
            (_teamId: string, { cursor, approval_token }: { cursor?: number; approval_token?: string }) =>
                Promise.resolve(
                    cursor === undefined
                        ? { ...projectsOn('laptop'), next_cursor: 100 }
                        : approval_token === 'token-1'
                          ? { status: 'ok', approval_token: null, projects: [later], next_cursor: null }
                          : { status: 'needs_approval', approval_token: 'token-1' }
                )
        )
        await expectLogic(logic, () => logic.actions.setMachine('laptop')).toFinishAllListeners()

        await expectLogic(logic, () => logic.actions.loadMoreProjects(undefined)).toFinishAllListeners()
        expect(logic.values).toMatchObject({
            projects: projectsOn('laptop').projects,
            pendingApproval: { kind: 'more-projects', approvalToken: 'token-1' },
        })

        await expectLogic(logic, () => logic.actions.allowPendingCall()).toFinishAllListeners()
        expect(logic.values).toMatchObject({
            projects: [...projectsOn('laptop').projects!, later],
            nextCursor: null,
            pendingApproval: null,
        })
        expect(projectsCreate).toHaveBeenLastCalledWith(String(logic.values.currentTeamId), {
            machine: 'laptop',
            cursor: 100,
            approval_token: 'token-1',
        })
    })

    it.each([
        [
            'answers',
            (reply: Deferred<T3CodeProjectsApi>) =>
                reply.resolve({
                    status: 'ok',
                    approval_token: null,
                    projects: [{ id: 'old-page', title: 'old page', has_default_model: true }],
                    next_cursor: null,
                }),
        ],
        ['fails', (reply: Deferred<T3CodeProjectsApi>) => reply.reject(new Error('The laptop is offline'))],
    ])(
        'ignores a later page asked for before the member left the machine and came back, when it %s late',
        async (_case, settleOldPage) => {
            const oldPage = deferred<T3CodeProjectsApi>()
            projectsCreate.mockImplementation(
                (_teamId: string, { machine, cursor }: { machine: string; cursor?: number }) =>
                    cursor === undefined
                        ? Promise.resolve({ ...projectsOn(machine), next_cursor: 100 })
                        : oldPage.promise
            )
            await expectLogic(logic, () => logic.actions.setMachine('laptop')).toFinishAllListeners()

            logic.actions.loadMoreProjects(undefined)
            logic.actions.setMachine('devbox')
            logic.actions.setMachine('laptop')
            await expectLogic(logic).toDispatchActions(['loadProjectsSuccess'])
            settleOldPage(oldPage)

            await expectLogic(logic).toFinishAllListeners()
            expect(logic.values).toMatchObject({
                projects: projectsOn('laptop').projects,
                nextCursor: 100,
                error: null,
            })
        }
    )

    it("shows the task as ready only while the step's webhook URL is still the created task's", async () => {
        const createdUrl = 'https://relay.example.com/hooks/laptop'
        projectsCreate.mockImplementation((_teamId: string, { machine }: { machine: string }) =>
            Promise.resolve(projectsOn(machine))
        )
        webhookTasksCreate.mockResolvedValue({ status: 'ok', approval_token: null, webhook_url: createdUrl })
        await expectLogic(logic, () => {
            logic.actions.setMachine('laptop')
            logic.actions.setProject('laptop-project')
            logic.actions.createTask({ title: 'PostHog: Signups' })
        }).toFinishAllListeners()
        expect(onWebhookUrl).toHaveBeenCalledWith(createdUrl)

        const withStepUrl = (webhookUrl: string | null): boolean =>
            t3CodeTaskSetupLogic({ actionId: 'action-1', onWebhookUrl, webhookUrl }).values.taskReady
        expect([withStepUrl(createdUrl), withStepUrl('https://example.com/other'), withStepUrl(null)]).toEqual([
            true,
            false,
            false,
        ])
    })

    it('drops the webhook URL of a task created for a selection the member left', async () => {
        projectsCreate.mockImplementation((_teamId: string, { machine }: { machine: string }) =>
            Promise.resolve(projectsOn(machine))
        )
        const task = deferred<T3CodeWebhookTaskApi>()
        webhookTasksCreate.mockReturnValue(task.promise)
        await expectLogic(logic, () => {
            logic.actions.setMachine('laptop')
            logic.actions.setProject('laptop-project')
        }).toFinishAllListeners()

        logic.actions.createTask({ title: 'PostHog: Signups' })
        logic.actions.setMachine('devbox')
        task.resolve({ status: 'ok', approval_token: null, webhook_url: 'https://relay.example.com/hooks/laptop' })

        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.createdWebhookUrl).toBeNull()
        expect(onWebhookUrl).not.toHaveBeenCalled()
    })
})
