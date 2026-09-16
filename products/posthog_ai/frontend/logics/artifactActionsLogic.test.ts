import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import type { VisualizationArtifactAction } from '../types/artifactActionTypes'
import { artifactActionsLogic } from './artifactActionsLogic'

describe('artifactActionsLogic', () => {
    let logic: ReturnType<typeof artifactActionsLogic.build>

    const action = (id: string, label: string): VisualizationArtifactAction => ({ id, label, onSelect: () => {} })

    beforeEach(() => {
        initKeaTests()
        logic = artifactActionsLogic()
        logic.mount()
    })

    afterEach(() => {
        logic?.unmount()
    })

    it('registers, upserts and deregisters a provider', async () => {
        await expectLogic(logic, () => {
            logic.actions.registerArtifactAction('notebook', action('add-to-notebook', 'Add to notebook'))
        }).toMatchValues({ visualizationActions: [expect.objectContaining({ id: 'add-to-notebook' })] })

        // A host that re-registers replaces its action instead of adding a second button.
        await expectLogic(logic, () => {
            logic.actions.registerArtifactAction('notebook', action('add-to-notebook', 'Add to this notebook'))
        }).toMatchValues({
            visualizationActions: [expect.objectContaining({ label: 'Add to this notebook' })],
        })

        await expectLogic(logic, () => {
            logic.actions.deregisterArtifactAction('notebook')
        }).toMatchValues({ visualizationActions: [] })
    })

    it('dedupes the same action id across providers, first writer wins', async () => {
        await expectLogic(logic, () => {
            logic.actions.registerArtifactAction('first', action('add-to-notebook', 'first'))
            logic.actions.registerArtifactAction('second', action('add-to-notebook', 'second'))
            logic.actions.registerArtifactAction('third', action('add-to-dashboard', 'third'))
        }).toMatchValues({
            visualizationActions: [
                expect.objectContaining({ label: 'first' }),
                expect.objectContaining({ label: 'third' }),
            ],
        })
    })
})
