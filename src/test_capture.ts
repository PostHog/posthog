/* global proto */
import { client } from './client'
import { struct } from 'pb-util'

const properties = {
    key: 'stringvalue',
    number: 123,
    bool: true,
}

const posthogEvent = {
    ip: '192.168.0.1',
    site_url: 'http://google.com',
    event: '$pageview',
    distinct_id: 'SOMELONGSTRING',
    team_id: 1,
    properties: struct.encode(properties),
    timestamp: 1312312312000,
}

client.OnCapture({ event: posthogEvent }, (error, { event }) => {
    if (!error) {
        console.log('successfully called oncapture')
        const properties = struct.decode(event.properties)
        console.log({ ...event, properties })
    } else {
        console.error(error)
    }
})
