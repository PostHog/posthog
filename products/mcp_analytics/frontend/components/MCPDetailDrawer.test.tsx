import { act, render } from '@testing-library/react'
import { useState } from 'react'

import { panelLayoutLogic } from '~/layout/panel-layout/panelLayoutLogic'
import { todayShellLogic } from '~/layout/today/todayShellLogic'
import { initKeaTests } from '~/test/init'

import { MCPDetailDrawer } from './MCPDetailDrawer'

function Drawers({ closed }: { closed: string[] }): JSX.Element {
    const [open, setOpen] = useState(['list', 'session'])
    const drawer = (name: string, stacked: boolean): JSX.Element | null =>
        open.includes(name) ? (
            <MCPDetailDrawer
                noun={name}
                title={name}
                position={null}
                onPrevious={null}
                onNext={null}
                stacked={stacked}
                onClose={() => {
                    closed.push(name)
                    setOpen((names) => names.filter((n) => n !== name))
                }}
                data-attr={name}
            >
                {name}
            </MCPDetailDrawer>
        ) : null
    return (
        <>
            {drawer('list', false)}
            {drawer('session', true)}
            {open.includes('session') ? drawer('call', true) : null}
            <button onClick={() => setOpen((names) => [...names, 'call'])}>Open call</button>
        </>
    )
}

describe('MCPDetailDrawer', () => {
    beforeEach(() => {
        initKeaTests()
        todayShellLogic.mount()
        panelLayoutLogic.mount()
    })

    it('closes only the drawer opened last on each Escape', () => {
        const closed: string[] = []
        const { getByText } = render(<Drawers closed={closed} />)
        act(() => getByText('Open call').click())
        const pressEscape = (): void =>
            act(() => {
                document.body.dispatchEvent(
                    new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true })
                )
            })

        pressEscape()
        expect(closed).toEqual(['call'])
        pressEscape()
        expect(closed).toEqual(['call', 'session'])
        pressEscape()
        expect(closed).toEqual(['call', 'session', 'list'])
    })
})
