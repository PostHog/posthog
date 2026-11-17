import { MakeLogicType, actions, kea, path, reducers } from 'kea'

interface investigationQuerySessionLogicValues {
    activeRequestId: string | null
}
interface investigationQuerySessionLogicActions {
    activateRequest: (id: string) => { id: string }
}
type investigationQuerySessionLogicType = MakeLogicType<
    investigationQuerySessionLogicValues,
    investigationQuerySessionLogicActions
>

export const investigationQuerySessionLogic = kea<investigationQuerySessionLogicType>([
    path(['products', 'notebooks', 'investigations', 'investigationQuerySessionLogic']),
    actions({ activateRequest: (id: string) => ({ id }) }),
    reducers({ activeRequestId: [null as string | null, { activateRequest: (_, { id }) => id }] }),
])
