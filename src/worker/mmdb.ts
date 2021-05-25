import { City } from '@maxmind/geoip2-node'
import net from 'net'
import { deserialize } from 'v8'

import { MMDB_INTERNAL_SERVER_TIMEOUT_SECONDS, MMDBRequestStatus } from '../config/mmdb-constants'
import { Hub } from '../types'

export async function fetchIpLocationInternally(ipAddress: string, server: Hub): Promise<City | null> {
    if (server.DISABLE_MMDB) {
        throw new Error(MMDBRequestStatus.ServiceUnavailable)
    }
    const mmdbRequestTimer = new Date()
    const result = await new Promise<City | null>((resolve, reject) => {
        const client = new net.Socket()
        client.connect(server.INTERNAL_MMDB_SERVER_PORT, 'localhost', () => {
            client.write(ipAddress)
            client.end()
        })

        client.on('data', (data) => {
            const result = deserialize(data)
            client.end(() => {
                if (typeof result !== 'string') {
                    // String means a RequestStatus error
                    resolve(result as City | null)
                } else {
                    reject(new Error(result))
                }
            })
        })

        client.setTimeout(MMDB_INTERNAL_SERVER_TIMEOUT_SECONDS * 1000).on('timeout', () => {
            client.destroy()
            reject(new Error(MMDBRequestStatus.TimedOut))
        })

        client.on('error', (error) => {
            client.destroy()
            if (error.message.includes('ECONNREFUSED')) {
                reject(new Error(MMDBRequestStatus.ServiceUnavailable))
            } else {
                reject(error)
            }
        })
    })
    server.statsd?.timing('mmdb.internal_request', mmdbRequestTimer)
    return result
}
