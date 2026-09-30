import { TaskRunDetailDTOApi } from '../generated/api.schemas'
import { TaskPullRequest, pullRequestLabel, splitPullRequests, taskPullRequests } from './taskPullRequests'

const pr = (repository: string, number: number): TaskPullRequest => ({
    url: `https://github.com/${repository}/pull/${number}`,
    repository,
    number,
})

const prs = (count: number): TaskPullRequest[] => Array.from({ length: count }, (_, index) => pr('org/app', index + 1))

describe('taskPullRequests', () => {
    it.each<[string, TaskRunDetailDTOApi['output'] | undefined, string[]]>([
        ['a run with no output shows no chip', null, []],
        ['a malformed URL does not crash the card', { pr_url: 'not a url' }, []],
        ['a non-GitHub host is not linked as a GitHub PR', { pr_url: 'https://gitlab.com/org/app/pull/1' }, []],
        ['a GitHub issue is not shown as a PR', { pr_url: 'https://github.com/org/app/issues/1' }, []],
        ['a lookalike path on another host is rejected', { pr_url: 'https://example.com/org/app/pull/1' }, []],
        [
            'a PR subpage and the PR itself collapse into one chip',
            { pr_url: 'https://github.com/org/app/pull/7', pr_urls: ['https://github.com/org/app/pull/7/files'] },
            ['https://github.com/org/app/pull/7'],
        ],
        [
            'multiple PRs keep the main pr_url first and skip non-strings',
            {
                pr_url: 'https://github.com/org/web/pull/9',
                pr_urls: ['https://github.com/org/app/pull/3', 42, 'https://github.com/org/web/pull/9'],
            },
            ['https://github.com/org/web/pull/9', 'https://github.com/org/app/pull/3'],
        ],
    ])('%s', (_, output, urls) => {
        expect(taskPullRequests(output).map((pullRequest) => pullRequest.url)).toEqual(urls)
    })

    it.each<[string, TaskPullRequest, string | null, string]>([
        ['the task repository drops the repo name', pr('org/app', 12), 'Org/App', '#12'],
        ['a task repository without the owner still matches', pr('org/app', 12), 'app', '#12'],
        ['a PR in another repository names that repo', pr('org/web', 12), 'org/app', 'web#12'],
        ['a task with no repository names the repo', pr('org/web', 12), null, 'web#12'],
    ])('labels %s', (_, pullRequest, taskRepository, label) => {
        expect(pullRequestLabel(pullRequest, taskRepository)).toEqual(label)
    })

    it.each([
        [2, 2, 0],
        [3, 2, 1],
        [5, 1, 4],
    ])('splits %i PRs into %i chips and %i behind the overflow chip', (count, visible, overflow) => {
        const split = splitPullRequests(prs(count))
        expect([split.visible.length, split.overflow.length]).toEqual([visible, overflow])
    })
})
