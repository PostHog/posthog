import type { SignalReportCheckApi } from 'products/signals/frontend/generated/api.schemas'

import { reportChecksLine, reportRunsLine } from './reportDetailLines'

describe('reportDetailLines', () => {
    const check = (status: string): SignalReportCheckApi => ({ status }) as SignalReportCheckApi

    it('puts a failed check in the closed line, so nobody has to open it', () => {
        expect(reportChecksLine([check('passed'), check('failed'), check('active')], '3 · next Aug 30')).toEqual({
            text: '1 of 3 failed',
            tone: 'risk',
        })
    })

    it('says what the checks wait for when none failed', () => {
        expect(reportChecksLine([check('pending')], '1 · waiting for resolve')).toEqual({
            text: '1 check · Waiting for resolve',
        })
    })

    test.each([
        [['completed'], '1 run · Finished'],
        [['live', 'completed'], '2 runs · The last one: in progress'],
        [[], '0 runs'],
    ] as const)('summarizes runs %j', (variants, expected) => {
        expect(reportRunsLine([...variants])).toBe(expected)
    })
})
