import { experimentLogic } from 'scenes/experiments/experimentLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { act, cleanup, fireEvent, render } from '~/test/reactTestingLibrary'
import type { Experiment } from '~/types'

import { ExperimentScoutModal } from './ExperimentScoutModal'

describe('ExperimentScoutModal', () => {
    const experimentId = 123
    let sourceLogic: ReturnType<typeof experimentLogic.build>
    let githubConnected: boolean
    let selfDrivingEnabled: boolean

    beforeEach(() => {
        githubConnected = false
        selfDrivingEnabled = false
        useMocks({
            get: {
                '/api/environments/:team_id/integrations/': () => [
                    200,
                    {
                        results: githubConnected
                            ? [
                                  {
                                      id: 7,
                                      kind: 'github',
                                      display_name: 'example-org',
                                      config: {},
                                      created_at: '2026-08-12T00:00:00Z',
                                  },
                              ]
                            : [],
                    },
                ],
                '/api/projects/:team_id/integrations/github/available_installations/': () => [
                    200,
                    { installations: [], personal_github_connected: false },
                ],
                '/api/projects/:team_id/signals/scout/metadata/current/': () => [
                    200,
                    { enrolled: true, banner_message: null, limits: {} },
                ],
                '/api/projects/:team_id/signals/scout/configs/': () => [200, []],
                '/api/projects/:team_id/signals/source_configs/': () => [
                    200,
                    {
                        count: selfDrivingEnabled ? 1 : 0,
                        results: selfDrivingEnabled
                            ? [
                                  {
                                      id: 'source-1',
                                      source_product: 'error_tracking',
                                      source_type: 'issue_created',
                                      enabled: true,
                                      config: {},
                                      created_at: '2026-08-12T00:00:00Z',
                                      updated_at: '2026-08-12T00:00:00Z',
                                      status: null,
                                  },
                              ]
                            : [],
                    },
                ],
            },
        })
        initKeaTests()
        sourceLogic = experimentLogic({ experimentId })
        sourceLogic.mount()
    })

    afterEach(() => {
        cleanup()
        sourceLogic.unmount()
    })

    it('opens Self-driving enablement before scout setup when the project is not ready', async () => {
        const { findByText, getByText } = render(<ExperimentScoutModal experimentId={experimentId} />)

        act(() => {
            sourceLogic.actions.launchExperimentSuccess({ id: experimentId } as Experiment)
        })

        expect(await findByText('Your experiment has been launched')).toBeTruthy()
        expect(getByText('What the scout watches')).toBeTruthy()
        expect(getByText('Data quality')).toBeTruthy()
        expect(getByText('Results')).toBeTruthy()

        fireEvent.click(getByText('Set up a scout'))

        expect(await findByText('Enable Self-driving')).toBeTruthy()
        expect(await findByText('Set up with the Wizard')).toBeTruthy()
        expect(await findByText('AI processing')).toBeTruthy()
        expect(await findByText('GitHub connection')).toBeTruthy()
        expect(await findByText('Connect account')).toBeTruthy()
    })

    it('goes directly to scout setup when Self-driving and its prerequisites are ready', async () => {
        githubConnected = true
        selfDrivingEnabled = true
        const { findByText, getByText } = render(<ExperimentScoutModal experimentId={experimentId} />)

        act(() => {
            sourceLogic.actions.launchExperimentSuccess({ id: experimentId } as Experiment)
        })

        expect(await findByText('Your experiment has been launched')).toBeTruthy()
        fireEvent.click(getByText('Set up a scout'))

        expect(await findByText('Set up an experiment scout')).toBeTruthy()
        expect(await findByText(/Step 3 of 3\. Review the instructions/)).toBeTruthy()
    })
})
