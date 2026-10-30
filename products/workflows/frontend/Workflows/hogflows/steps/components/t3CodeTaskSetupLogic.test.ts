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
        logic = t3CodeTaskSetupLogic({ actionId: 'action-1', onWebhookUrl })
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
