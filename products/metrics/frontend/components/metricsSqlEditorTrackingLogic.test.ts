import { expectLogic } from 'kea-test-utils'

import { teamLogic } from 'scenes/teamLogic'

import { ProductIntentContext, ProductKey } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

import { metricsSqlEditorTrackingLogic } from './metricsSqlEditorTrackingLogic'

jest.mock('posthog-js')

// endpointLogic (pulled in transitively via sqlEditorLogic) uses permanentlyMount() with a
// keyed logic, which crashes in tests without the full React component tree.
jest.mock('lib/utils/kea-logic-builders', () => ({
    ...jest.requireActual('lib/utils/kea-logic-builders'),
    permanentlyMount: () => () => {},
}))

describe('metricsSqlEditorTrackingLogic', () => {
    let logic: ReturnType<typeof metricsSqlEditorTrackingLogic.build>

    // teamLogic is mounted via connect once `logic` mounts, so its actionCreators are available here.
    const sqlRunIntent = (): any =>
        teamLogic.actionCreators.addProductIntent({
            product_type: ProductKey.METRICS,
            intent_context: ProductIntentContext.METRICS_SQL_QUERY_RUN,
        })

    beforeEach(() => {
        initKeaTests()
        logic = metricsSqlEditorTrackingLogic({ sqlEditorTabId: 'test-tab' })
        logic.mount()
    })

    afterEach(() => {
        logic?.unmount()
    })

    // The intent feeds the growth team's activation funnel; a renamed or disconnected
    // sqlEditorLogic action would silently stop recording it. The auto-init first run is
    // skipped so it isn't counted as user intent. (Save-as intents aren't covered here:
    // dispatching the real submit actions needs the full data-node logic graph mounted.)
    it('a manual query run records a product intent, the auto-init first run does not', async () => {
        await expectLogic(logic, () => {
            logic.actions.sqlEditorRunQuery()
        }).toNotHaveDispatchedActions([sqlRunIntent()])

        await expectLogic(logic, () => {
            logic.actions.sqlEditorRunQuery()
        }).toDispatchActions([sqlRunIntent()])
    })
})
