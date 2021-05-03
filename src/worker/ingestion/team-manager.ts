import { Properties } from '@posthog/plugin-scaffold'
import { nodePostHog } from 'posthog-js-lite/dist/src/targets/node'

import { Team, TeamId } from '../../types'
import { DB } from '../../utils/db/db'
import { timeoutGuard } from '../../utils/db/utils'
import { UUIDT } from '../../utils/utils'

type TeamCache<T> = Map<TeamId, [T, number]>

export class TeamManager {
    db: DB
    teamCache: TeamCache<Team | null>
    eventNamesCache: Map<TeamId, Set<string>>
    eventPropertiesCache: Map<TeamId, Set<string>>
    shouldSendWebhooksCache: TeamCache<boolean>

    constructor(db: DB) {
        this.db = db
        this.teamCache = new Map()
        this.eventNamesCache = new Map()
        this.eventPropertiesCache = new Map()
        this.shouldSendWebhooksCache = new Map()
    }

    public async fetchTeam(teamId: number): Promise<Team | null> {
        const cachedTeam = this.getByAge(this.teamCache, teamId)
        if (cachedTeam) {
            return cachedTeam
        }

        const timeout = timeoutGuard(`Still running "fetchTeam". Timeout warning after 30 sec!`)
        try {
            const teamQueryResult = await this.db.postgresQuery(
                'SELECT * FROM posthog_team WHERE id = $1',
                [teamId],
                'selectTeam'
            )
            const team: Team | null = teamQueryResult.rows[0] || null

            this.teamCache.set(teamId, [team, Date.now()])
            return team
        } finally {
            clearTimeout(timeout)
        }
    }

    public async shouldSendWebhooks(teamId: number): Promise<boolean> {
        const cachedValue = this.getByAge(this.shouldSendWebhooksCache, teamId)
        if (cachedValue !== undefined) {
            return cachedValue
        }

        const team = await this.fetchTeam(teamId)
        if (!team) {
            this.shouldSendWebhooksCache.set(teamId, [false, Date.now()])
            return false
        }
        if (!!team.slack_incoming_webhook) {
            this.shouldSendWebhooksCache.set(teamId, [true, Date.now()])
            return true
        }

        const timeout = timeoutGuard(`Still running "shouldSendWebhooks". Timeout warning after 30 sec!`)
        try {
            const hookQueryResult = await this.db.postgresQuery(
                `SELECT COUNT(*) FROM ee_hook WHERE team_id = $1 AND event = 'action_performed' LIMIT 1`,
                [team.id],
                'shouldSendHooksTask'
            )
            const hasHooks = parseInt(hookQueryResult.rows[0].count) > 0
            this.shouldSendWebhooksCache.set(teamId, [hasHooks, Date.now()])
            return hasHooks
        } catch (error) {
            // In FOSS PostHog ee_hook does not exist. If the error is other than that, rethrow it
            if (String(error).includes('relation "ee_hook" does not exist')) {
                this.shouldSendWebhooksCache.set(teamId, [false, Date.now()])
                return false
            }
            throw error
        } finally {
            clearTimeout(timeout)
        }
    }

    public async updateEventNamesAndProperties(
        teamId: number,
        event: string,
        properties: Properties,
        posthog: ReturnType<typeof nodePostHog>
    ): Promise<void> {
        const team: Team | null = await this.fetchTeam(teamId)

        if (!team) {
            return
        }

        const timeout = timeoutGuard('Still running "updateEventNamesAndProperties". Timeout warning after 30 sec!', {
            event: event,
            ingested: team.ingested_event,
        })

        await this.cacheEventNamesAndProperties(team.id)

        if (!this.eventNamesCache.get(team.id)?.has(event)) {
            await this.db.postgresQuery(
                `INSERT INTO posthog_eventdefinition (id, name, volume_30_day, query_usage_30_day, team_id) VALUES ($1, $2, NULL, NULL, $3) ON CONFLICT DO NOTHING`,
                [new UUIDT().toString(), event, team.id],
                'insertEventDefinition'
            )
            this.eventNamesCache.get(team.id)?.add(event)
        }

        for (const [key, value] of Object.entries(properties)) {
            if (!this.eventPropertiesCache.get(team.id)?.has(key)) {
                await this.db.postgresQuery(
                    `INSERT INTO posthog_propertydefinition (id, name, is_numerical, volume_30_day, query_usage_30_day, team_id) VALUES ($1, $2, $3, NULL, NULL, $4) ON CONFLICT DO NOTHING`,
                    [new UUIDT().toString(), key, typeof value === 'number', team.id],
                    'insertPropertyDefinition'
                )
                this.eventPropertiesCache.get(team.id)?.add(key)
            }
        }

        if (team && !team.ingested_event) {
            await this.db.postgresQuery(
                `UPDATE posthog_team SET ingested_event = $1 WHERE id = $2`,
                [true, team.id],
                'setTeamIngestedEvent'
            )

            // First event for the team captured
            const organizationMembers = await this.db.postgresQuery(
                'SELECT distinct_id FROM posthog_user JOIN posthog_organizationmembership ON posthog_user.id = posthog_organizationmembership.user_id WHERE organization_id = $1',
                [team.organization_id],
                'posthog_organizationmembership'
            )
            const distinctIds: { distinct_id: string }[] = organizationMembers.rows
            for (const { distinct_id } of distinctIds) {
                posthog.identify(distinct_id)
                posthog.capture('first team event ingested', {
                    team: team.uuid,
                    sdk: properties.$lib,
                    realm: properties.realm,
                    host: properties.$host,
                })
            }
        }
        clearTimeout(timeout)
    }

    public async cacheEventNamesAndProperties(teamId: number): Promise<void> {
        let eventNamesCache = this.eventNamesCache.get(teamId)
        if (!eventNamesCache) {
            const eventNames = await this.db.postgresQuery(
                'SELECT name FROM posthog_eventdefinition WHERE team_id = $1',
                [teamId],
                'fetchEventDefinitions'
            )
            eventNamesCache = new Set(eventNames.rows.map((r) => r.name))
            this.eventNamesCache.set(teamId, eventNamesCache)
        }

        let eventPropertiesCache = this.eventPropertiesCache.get(teamId)
        if (!eventPropertiesCache) {
            const eventProperties = await this.db.postgresQuery(
                'SELECT name FROM posthog_propertydefinition WHERE team_id = $1',
                [teamId],
                'fetchPropertyDefinitions'
            )
            eventPropertiesCache = new Set(eventProperties.rows.map((r) => r.name))
            this.eventPropertiesCache.set(teamId, eventPropertiesCache)
        }
    }

    private getByAge<K, V>(cache: Map<K, [V, number]>, key: K, maxAgeMs = 30_000): V | undefined {
        if (cache.has(key)) {
            const [value, age] = cache.get(key)!
            if (Date.now() - age <= maxAgeMs) {
                return value
            }
        }
        return undefined
    }
}
