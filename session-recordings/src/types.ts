export type Event = {
    uuid: string
    team_id: string
    timestamp: number
    event: string
    data: string
}

export type EventData = {
    properties: {
        $session_id: string
        $window_id: string
        $snapshot_data: { data: string }
    }
}

export type SessionData = any[]
