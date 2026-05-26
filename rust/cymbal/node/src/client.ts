import type { MessageInitShape, MessageShape } from '@bufbuild/protobuf'
import type { Client, Transport } from '@connectrpc/connect'
import { createClient } from '@connectrpc/connect'
import { createGrpcTransport } from '@connectrpc/connect-node'

import {
    CymbalIngestion,
    ProcessExceptionBatchRequestSchema,
    ProcessExceptionBatchResultSchema,
} from './generated/cymbal/v1/pipeline_pb'

export const SUPPORTED_CYMBAL_INGESTION_API_VERSIONS = ['v1'] as const
export type CymbalIngestionApiVersion = (typeof SUPPORTED_CYMBAL_INGESTION_API_VERSIONS)[number]

const DEFAULT_API_VERSION: CymbalIngestionApiVersion = 'v1'
const INGESTION_SERVICES = {
    v1: CymbalIngestion,
} satisfies Record<CymbalIngestionApiVersion, typeof CymbalIngestion>

export interface CymbalIngestionClientConfig {
    /** Host and port of the Cymbal gRPC server, e.g. "localhost:50051". */
    addr: string
    /** Use TLS for the HTTP/2 connection. Default: false. */
    useTls?: boolean
    /** Cymbal ingestion API version to call. Default: "v1". */
    apiVersion?: CymbalIngestionApiVersion
    /** Per-request timeout in milliseconds. */
    timeoutMs?: number
    /** Maximum inbound message size in bytes. */
    readMaxBytes?: number
    /** Maximum outbound message size in bytes. */
    writeMaxBytes?: number
}

export interface ProcessExceptionBatchOptions {
    signal?: AbortSignal
}

export type ProcessExceptionBatchRequestInit = MessageInitShape<typeof ProcessExceptionBatchRequestSchema>
export type ProcessExceptionBatchResultMessage = MessageShape<typeof ProcessExceptionBatchResultSchema>

export class CymbalIngestionClient {
    private readonly client: Client<typeof CymbalIngestion>

    private constructor(
        transport: Transport,
        readonly apiVersion: CymbalIngestionApiVersion
    ) {
        this.client = createClient(INGESTION_SERVICES[apiVersion], transport)
    }

    static fromTransport(
        transport: Transport,
        apiVersion: CymbalIngestionApiVersion = DEFAULT_API_VERSION
    ): CymbalIngestionClient {
        return new CymbalIngestionClient(transport, apiVersion)
    }

    static fromConfig(config: CymbalIngestionClientConfig): CymbalIngestionClient {
        const scheme = config.useTls ? 'https' : 'http'
        const transport = createGrpcTransport({
            baseUrl: `${scheme}://${config.addr}`,
            defaultTimeoutMs: config.timeoutMs,
            readMaxBytes: config.readMaxBytes,
            writeMaxBytes: config.writeMaxBytes,
        })
        return new CymbalIngestionClient(transport, config.apiVersion ?? DEFAULT_API_VERSION)
    }

    processExceptionBatch(
        request: ProcessExceptionBatchRequestInit,
        options: ProcessExceptionBatchOptions = {}
    ): AsyncIterable<ProcessExceptionBatchResultMessage> {
        return this.client.processExceptionBatch(request, { signal: options.signal })
    }
}
