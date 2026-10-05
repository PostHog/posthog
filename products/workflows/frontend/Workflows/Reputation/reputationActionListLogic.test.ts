import { router } from 'kea-router'
import { expectLogic, partial } from 'kea-test-utils'

import { supportLogic } from 'lib/components/Support/supportLogic'
import { urls } from 'scenes/urls'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { reputationActionListLogic } from './reputationActionListLogic'
import { HEALTHY, NEEDS_WORK, reputationMocks } from './reputationFixtures'
import { reputationResponseLogic } from './reputationResponseLogic'

describe('reputationActionListLogic', () => {
    let logic: ReturnType<typeof reputationActionListLogic.build>

    beforeEach(() => {
        initKeaTests()
    })

    async function mountLogic(path?: string): Promise<void> {
        if (path) {
            router.actions.push(path)
        }
        logic = reputationActionListLogic()
        logic.mount()
        await expectLogic(reputationResponseLogic).toDispatchActions(['loadReputationSuccess'])
    }

    afterEach(() => {
        logic.unmount()
    })

    it('lists what to fix worst first, pointing each item where it gets fixed', async () => {
        useMocks(reputationMocks(NEEDS_WORK))
        await mountLogic()

        expect(logic.values.reputationActions).toEqual([
            partial({
                key: 'paused:wf-win-back',
                severity: 'high',
                cta: partial({ to: `${urls.workflow('wf-win-back', 'workflow')}?node=trigger_node` }),
            }),
            partial({
                key: 'finding:BOUNCE',
                severity: 'high',
                cta: partial({ to: `${urls.workflow('wf-import', 'workflow')}?node=trigger_node` }),
            }),
            partial({
                key: 'workflow-bounce:wf-onboarding',
                severity: 'medium',
                cta: partial({ to: `${urls.workflow('wf-onboarding', 'workflow')}?node=trigger_node` }),
            }),
            partial({
                key: 'finding:DMARC',
                severity: 'medium',
                cta: partial({ to: urls.workflows('channels') }),
            }),
            partial({
                key: 'provider-bounce:Yahoo',
                severity: 'low',
            }),
        ])
        expect(logic.values.providersOverLineCount).toBe(1)
    })

    it('has nothing to fix for a healthy project', async () => {
        useMocks(reputationMocks(HEALTHY))
        await mountLogic()

        expect(logic.values.reputationActions).toEqual([])
    })

    it.each([
        [urls.workflows('reputation'), urls.workflows('channels')],
        [urls.broadcasts('reputation'), urls.broadcasts('channels')],
    ])('keeps the fix links on the surface of %s', async (path, channelsUrl) => {
        useMocks(reputationMocks(NEEDS_WORK))
        await mountLogic(path)

        expect(logic.values.reputationActions.find((item) => item.key === 'finding:DMARC')?.cta).toEqual({
            label: 'Open channels',
            to: channelsUrl,
        })
    })

    it('opens the breakdown tab an on-page button names', async () => {
        useMocks(reputationMocks(NEEDS_WORK))
        await mountLogic()

        await expectLogic(logic, () => logic.actions.runActionCta('provider-bounce:Yahoo'))
            .toDispatchActions(['showBreakdown'])
            .toMatchValues({ activeBreakdownTab: 'providers' })
    })

    it('opens the support form with a prefilled message', async () => {
        useMocks(reputationMocks({ ...HEALTHY, aws: { health: 'critical', sending_status: 'DISABLED', findings: [] } }))
        await mountLogic()

        await expectLogic(logic, () => logic.actions.runActionCta('provider-status')).toDispatchActions([
            supportLogic.actionCreators.openSupportForm({
                kind: 'support',
                message:
                    'Our email provider paused sending for this project. Please review it and re-enable sending. What I changed to lower our bounce and spam complaint rates: ',
            }),
        ])
    })
})
