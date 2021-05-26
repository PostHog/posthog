import { Action, PluginsServerConfig } from '../../types'
import { DB } from '../../utils/db/db'
import { status } from '../../utils/status'

type ActionCache = Record<Action['id'], Action>

export class ActionManager {
    private ready: boolean
    private db: DB
    private actionCache: ActionCache

    constructor(db: DB) {
        this.ready = false
        this.db = db
        this.actionCache = {}
    }

    public async prepare(): Promise<void> {
        await this.reloadAllActions()
        this.ready = true
    }

    public getAction(id: Action['id']): Action | undefined {
        if (!this.ready) {
            throw new Error('ActionManager is not ready! Run actionManager.prepare() before this')
        }
        return this.actionCache[id]
    }

    public async reloadAllActions(): Promise<void> {
        this.actionCache = await this.db.fetchAllActionsMap()
        status.info('🍿', 'Fetched all actions from DB anew')
    }

    public async reloadAction(id: Action['id']): Promise<void> {
        const refetchedAction = await this.db.fetchAction(id)
        if (refetchedAction) {
            status.info(
                '🍿',
                id in this.actionCache ? `Refetched action ID ${id} from DB` : `Fetched new action ID ${id} from DB`
            )
            this.actionCache[id] = refetchedAction
        } else if (id in this.actionCache) {
            status.info(
                '🍿',
                `Tried to fetch action ID ${id} from DB, but it wasn't found in DB, so deleted from cache instead`
            )
            delete this.actionCache[id]
        } else {
            status.info(
                '🍿',
                `Tried to fetch action ID ${id} from DB, but it wasn't found in DB or cache, so did nothing instead`
            )
        }
    }

    public dropAction(id: Action['id']): void {
        if (id in this.actionCache) {
            status.info('🍿', `Deleted action ID ${id} from cache`)
            delete this.actionCache[id]
        } else {
            status.info(
                '🍿',
                `Tried to delete action ID ${id} from cache, but it wasn't found in cache, so did nothing instead`
            )
        }
    }
}
