import { MOCK_DEFAULT_BASIC_USER, MOCK_DEFAULT_TEAM } from '~/lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'
import { LLMPromptVersionSummary } from '~/types'

import {
    experimentsCreateFromPromptCreate,
    experimentsPromptTemplatesRetrieve,
} from '../../../experiments/frontend/generated/api'
import { createPromptExperimentModalLogic } from './createPromptExperimentModalLogic'

jest.mock('../../../experiments/frontend/generated/api', () => ({
    experimentsCreateFromPromptCreate: jest.fn(),
    experimentsPromptTemplatesRetrieve: jest.fn(),
}))

const mockExperimentsCreateFromPromptCreate = experimentsCreateFromPromptCreate as jest.MockedFunction<
    typeof experimentsCreateFromPromptCreate
>
const mockExperimentsPromptTemplatesRetrieve = experimentsPromptTemplatesRetrieve as jest.MockedFunction<
    typeof experimentsPromptTemplatesRetrieve
>

const MOCK_TEMPLATES = [
    { key: 'cost', label: 'Cost', description: 'Cost template' },
    { key: 'latency', label: 'Latency', description: 'Latency template' },
    { key: 'eval_pass_rate', label: 'Eval pass rate', description: 'Eval template' },
]

const MOCK_PROMPT_NAME = 'test-prompt'
const MOCK_VERSIONS: LLMPromptVersionSummary[] = [
    { id: 'v3', version: 3, created_by: MOCK_DEFAULT_BASIC_USER, created_at: '2025-01-15T00:00:00Z', is_latest: true },
    {
        id: 'v2',
        version: 2,
        created_by: MOCK_DEFAULT_BASIC_USER,
        created_at: '2025-01-10T00:00:00Z',
        is_latest: false,
    },
    {
        id: 'v1',
        version: 1,
        created_by: MOCK_DEFAULT_BASIC_USER,
        created_at: '2025-01-01T00:00:00Z',
        is_latest: false,
    },
]

describe('createPromptExperimentModalLogic', () => {
    let logic: ReturnType<typeof createPromptExperimentModalLogic.build>

    beforeEach(() => {
        initKeaTests()
        jest.resetAllMocks()
        mockExperimentsPromptTemplatesRetrieve.mockResolvedValue(MOCK_TEMPLATES)
        mockExperimentsCreateFromPromptCreate.mockResolvedValue({
            id: 42,
            // The full Experiment type has many fields; the modal only needs id.
            // Cast to silence the test mock type expectations.
        } as any)

        logic = createPromptExperimentModalLogic()
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
    })

    it('opens the modal and seeds two empty version slots', async () => {
        logic.actions.openModal(MOCK_PROMPT_NAME, MOCK_VERSIONS)
        // selectedTemplates is pre-filled from templates after they load — assert other fields
        // here and test the auto-select behavior separately.
        await expectLogic(logic).toMatchValues({
            isModalOpen: true,
            promptName: MOCK_PROMPT_NAME,
            promptVersions: MOCK_VERSIONS,
            versionSlots: [null, null],
        })
    })

    it('pre-selects every template once they finish loading', async () => {
        logic.actions.openModal(MOCK_PROMPT_NAME, MOCK_VERSIONS)
        await expectLogic(logic).toFinishAllListeners()
        await expectLogic(logic).toMatchValues({
            selectedTemplates: ['cost', 'latency', 'eval_pass_rate'],
        })
    })

    it('submitCreate posts only the templates that are still selected after toggling', async () => {
        logic.actions.openModal(MOCK_PROMPT_NAME, MOCK_VERSIONS)
        await expectLogic(logic).toFinishAllListeners()

        logic.actions.setVersionAt(0, 1)
        logic.actions.setVersionAt(1, 2)
        // Clear the pre-selection, then opt back into a single template.
        logic.actions.setSelectedTemplates([])
        logic.actions.toggleTemplate('cost')

        await expectLogic(logic, () => {
            logic.actions.submitCreate()
        }).toFinishAllListeners()

        expect(mockExperimentsCreateFromPromptCreate).toHaveBeenCalledWith(String(MOCK_DEFAULT_TEAM.id), {
            prompt_name: MOCK_PROMPT_NAME,
            versions: [1, 2],
            templates: ['cost'],
        })
    })

    it('submitCreate posts all selected templates in toggle order', async () => {
        logic.actions.openModal(MOCK_PROMPT_NAME, MOCK_VERSIONS)
        await expectLogic(logic).toFinishAllListeners()

        logic.actions.setVersionAt(0, 1)
        logic.actions.setVersionAt(1, 2)
        logic.actions.setSelectedTemplates([])
        logic.actions.toggleTemplate('cost')
        logic.actions.toggleTemplate('latency')
        logic.actions.toggleTemplate('eval_pass_rate')

        await expectLogic(logic, () => {
            logic.actions.submitCreate()
        }).toFinishAllListeners()

        expect(mockExperimentsCreateFromPromptCreate).toHaveBeenCalledWith(String(MOCK_DEFAULT_TEAM.id), {
            prompt_name: MOCK_PROMPT_NAME,
            versions: [1, 2],
            templates: ['cost', 'latency', 'eval_pass_rate'],
        })
    })

    it('toggleTemplate removes a template that is already selected', async () => {
        logic.actions.openModal(MOCK_PROMPT_NAME, MOCK_VERSIONS)
        await expectLogic(logic).toFinishAllListeners()

        // After load, all templates are auto-selected; toggling removes the named one.
        logic.actions.toggleTemplate('cost')
        await expectLogic(logic).toMatchValues({ selectedTemplates: ['latency', 'eval_pass_rate'] })

        logic.actions.toggleTemplate('cost')
        await expectLogic(logic).toMatchValues({ selectedTemplates: ['latency', 'eval_pass_rate', 'cost'] })
    })

    it('canSubmit is false until two distinct versions and at least one template are picked', async () => {
        logic.actions.openModal(MOCK_PROMPT_NAME, MOCK_VERSIONS)
        await expectLogic(logic).toFinishAllListeners()
        // Start from an empty template selection so we exercise the can-submit transitions.
        logic.actions.setSelectedTemplates([])
        await expectLogic(logic).toMatchValues({ canSubmit: false })

        logic.actions.setVersionAt(0, 1)
        await expectLogic(logic).toMatchValues({ canSubmit: false })

        logic.actions.setVersionAt(1, 1) // duplicate
        await expectLogic(logic).toMatchValues({ canSubmit: false })

        logic.actions.setVersionAt(1, 2)
        await expectLogic(logic).toMatchValues({ canSubmit: false }) // still needs at least one template

        logic.actions.toggleTemplate('cost')
        await expectLogic(logic).toMatchValues({ canSubmit: true })

        // Deselecting the last template should make submit invalid again.
        logic.actions.toggleTemplate('cost')
        await expectLogic(logic).toMatchValues({ canSubmit: false })
    })

    // Regression: adding an empty slot should immediately re-disable submit, even though
    // selectedVersions still satisfies MIN_VERSIONS (the null slot was being silently
    // dropped from the submitted payload).
    it('canSubmit is false when any slot is unfilled', async () => {
        logic.actions.openModal(MOCK_PROMPT_NAME, MOCK_VERSIONS)
        await expectLogic(logic).toFinishAllListeners()
        logic.actions.setSelectedTemplates([])

        logic.actions.setVersionAt(0, 1)
        logic.actions.setVersionAt(1, 2)
        logic.actions.toggleTemplate('cost')
        await expectLogic(logic).toMatchValues({ canSubmit: true })

        logic.actions.addVersionSlot()
        await expectLogic(logic).toMatchValues({ canSubmit: false })

        logic.actions.setVersionAt(2, 3)
        await expectLogic(logic).toMatchValues({ canSubmit: true })
    })

    it('addVersionSlot grows the list and removeVersionSlot shrinks it', async () => {
        logic.actions.openModal(MOCK_PROMPT_NAME, MOCK_VERSIONS)
        logic.actions.setVersionAt(0, 1)
        logic.actions.setVersionAt(1, 2)
        logic.actions.addVersionSlot()
        await expectLogic(logic).toMatchValues({ versionSlots: [1, 2, null] })

        logic.actions.removeVersionSlot(2)
        await expectLogic(logic).toMatchValues({ versionSlots: [1, 2] })
    })

    it('removeVersionSlot will not go below two rows', async () => {
        logic.actions.openModal(MOCK_PROMPT_NAME, MOCK_VERSIONS)
        logic.actions.setVersionAt(0, 1)
        logic.actions.setVersionAt(1, 2)
        logic.actions.removeVersionSlot(0)
        await expectLogic(logic).toMatchValues({ versionSlots: [1, 2] })
    })

    it('loads templates when modal opens', async () => {
        logic.actions.openModal(MOCK_PROMPT_NAME, MOCK_VERSIONS)
        await expectLogic(logic).toFinishAllListeners()
        expect(mockExperimentsPromptTemplatesRetrieve).toHaveBeenCalledWith(String(MOCK_DEFAULT_TEAM.id))
        await expectLogic(logic).toMatchValues({ templates: MOCK_TEMPLATES })
    })
})
