import { logsAlertsDestinationsDeleteCreate, logsAlertsRetrieve } from 'products/logs/frontend/generated/api'
import { LogsAlertConfigurationDetailApi } from 'products/logs/frontend/generated/api.schemas'

import { logsAlertDestinationsLogicProps } from '../logsAlertDestinations'

jest.mock('products/logs/frontend/generated/api', () => ({
    logsAlertsRetrieve: jest.fn(),
    logsAlertsDestinationsCreate: jest.fn(),
    logsAlertsDestinationsDeleteCreate: jest.fn(),
}))

const mockRetrieve = logsAlertsRetrieve as jest.MockedFunction<typeof logsAlertsRetrieve>
const mockDelete = logsAlertsDestinationsDeleteCreate as jest.MockedFunction<typeof logsAlertsDestinationsDeleteCreate>

describe('logs alert destinations api', () => {
    const api = logsAlertDestinationsLogicProps('alert-1').api!

    test.each([
        ['an older destination by its HogFunctions', null, ['fn-1', 'fn-2'], { hog_function_ids: ['fn-1', 'fn-2'] }],
        ['a destination with both by its HogFunctions', 'row-1', ['fn-1'], { hog_function_ids: ['fn-1'] }],
        ['a destination whose HogFunctions are gone by its id', 'row-1', [], { destination_ids: ['row-1'] }],
    ])('deletes %s', async (_name, id, hogFunctionIds, body) => {
        mockRetrieve.mockResolvedValue({
            destinations: [
                { id, hog_function_ids: hogFunctionIds, type: 'slack', enabled: true, message_customized: false },
            ],
        } as unknown as LogsAlertConfigurationDetailApi)

        const [destination] = await api.list('1', 'alert-1')
        await api.remove('1', 'alert-1', destination)

        expect(destination.id).toBeTruthy()
        expect(mockDelete).toHaveBeenLastCalledWith('1', 'alert-1', body)
    })
})
