import { render } from '@testing-library/react'
import { ComponentType } from 'react'

import { IconCloud, IconLaptop, IconListCheck } from '@posthog/icons'

import { IconSlack } from 'lib/lemon-ui/icons'

import { TaskRunEnvironment } from '../types/taskTypes'
import { TaskSourceIcon } from './TaskSourceIcon'
import { getTaskSourceTooltip } from './taskSourceMeta'

type DisplayCase = [string, string | undefined, TaskRunEnvironment | undefined, ComponentType]

const displayCases: DisplayCase[] = [
    ['a mapped origin wins over the environment', 'slack', TaskRunEnvironment.LOCAL, IconSlack],
    ['an unmapped origin falls back to the cloud icon', 'user_created', TaskRunEnvironment.CLOUD, IconCloud],
    ['an unmapped origin falls back to the laptop icon', 'user_created', TaskRunEnvironment.LOCAL, IconLaptop],
    ['a task without a run falls back to the generic icon', undefined, undefined, IconListCheck],
]

function markup(element: JSX.Element): string {
    return render(element).container.innerHTML
}

describe('TaskSourceIcon', () => {
    it.each(displayCases)('%s', (_name, originProduct, environment, ExpectedIcon) => {
        expect(markup(<TaskSourceIcon originProduct={originProduct} environment={environment} />)).toBe(
            markup(<ExpectedIcon />)
        )
    })

    it.each([
        ['slack', TaskRunEnvironment.CLOUD, 'From Slack · Cloud task'],
        ['user_created', TaskRunEnvironment.CLOUD, 'Cloud task'],
        ['user_created', TaskRunEnvironment.LOCAL, 'Local task'],
        [undefined, undefined, 'Task'],
    ] as [string | undefined, TaskRunEnvironment | undefined, string][])(
        'names the source before the environment in the tooltip for %s',
        (originProduct, environment, expected) => {
            expect(getTaskSourceTooltip(originProduct, environment)).toBe(expected)
        }
    )
})
