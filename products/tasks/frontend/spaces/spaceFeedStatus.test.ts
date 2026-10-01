import { TaskRunDetailDTOApi } from '../generated/api.schemas'
import { spaceFeedStatus } from './spaceFeedStatus'

const run = (status: string, environment: string, output: TaskRunDetailDTOApi['output'] = null): TaskRunDetailDTOApi =>
    ({ status, environment, output }) as TaskRunDetailDTOApi

describe('spaceFeedStatus', () => {
    it.each([
        ['no run', null, 'Draft'],
        ['a cloud run in progress', run('in_progress', 'cloud'), 'In progress'],
        ['a local run in progress', run('in_progress', 'local'), null],
        ['a local run that completed', run('completed', 'local'), 'Ready'],
        [
            'a run with a pull request',
            run('in_progress', 'local', { pr_url: 'https://example.com/pull/1' }),
            'PR ready',
        ],
        [
            'a run with a listed pull request',
            run('completed', 'cloud', { pr_urls: ['https://example.com/pull/2'] }),
            'PR ready',
        ],
        [
            'a failed run with a pull request',
            run('failed', 'cloud', { pr_url: 'https://example.com/pull/3' }),
            'Failed',
        ],
    ])('labels %s', (_, latestRun, label) => {
        expect(spaceFeedStatus(latestRun)?.label ?? null).toEqual(label)
    })

    it.each([
        ['merged', 'Merged'],
        ['closed', 'Closed'],
        ['draft', 'Draft PR'],
        ['unknown', 'PR ready'],
    ] as const)('labels a run whose pull request is %s', (prState, label) => {
        const latestRun = run('completed', 'cloud', { pr_url: 'https://github.com/org/app/pull/1' })
        expect(spaceFeedStatus(latestRun, prState)?.label).toEqual(label)
    })
})
