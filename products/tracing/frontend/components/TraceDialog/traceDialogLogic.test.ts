import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import { traceDialogLogic } from './traceDialogLogic'

describe('traceDialogLogic', () => {
    let logic: ReturnType<typeof traceDialogLogic.build>

    beforeEach(() => {
        initKeaTests()
        router.actions.push('/logs')
        logic = traceDialogLogic()
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
    })

    it('keeps the trace after close so the exit animation does not flash an empty dialog', async () => {
        logic.actions.openTraceDialog({ traceId: 'abc123', spanId: 'def456' })

        await expectLogic(logic, () => {
            logic.actions.closeTraceDialog()
        }).toMatchValues({ isOpen: false, trace: { traceId: 'abc123', spanId: 'def456' } })
    })

    it.each([
        ['stays open on a query-only change', '/logs?filters=abc', true],
        ['stays open on a hash-only change', '/logs#panel', true],
        ['closes on a new pathname', '/insights', false],
    ])('%s', async (_name, url, expectedOpen) => {
        logic.actions.openTraceDialog({ traceId: 'abc123' })

        await expectLogic(logic, () => {
            router.actions.push(url)
        }).toMatchValues({ isOpen: expectedOpen })
    })
})
