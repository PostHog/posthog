import { render } from '@testing-library/react'

import { HogFlowEditorPanelVariables } from './HogFlowEditorPanelVariables'

jest.mock('kea', () => ({
    useValues: () => ({
        workflow: {
            id: 'test-workflow',
            variables: [
                { key: 'short', label: 'short', type: 'string', default: '' },
                {
                    key: 'a_much_longer_variable_name',
                    label: 'a_much_longer_variable_name',
                    type: 'string',
                    default: 'some default',
                },
            ],
        },
    }),
    useActions: () => ({
        setWorkflowInfo: jest.fn(),
    }),
}))

jest.mock('../hogFlowEditorLogic', () => ({
    hogFlowEditorLogic: {},
}))

describe('HogFlowEditorPanelVariables', () => {
    it('renders variable rows with stable column widths', () => {
        const { container } = render(<HogFlowEditorPanelVariables />)
        expect(container).toMatchSnapshot()
    })
})
