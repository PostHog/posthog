"use strict";
var __awaiter = (this && this.__awaiter) || function (thisArg, _arguments, P, generator) {
    function adopt(value) { return value instanceof P ? value : new P(function (resolve) { resolve(value); }); }
    return new (P || (P = Promise))(function (resolve, reject) {
        function fulfilled(value) { try { step(generator.next(value)); } catch (e) { reject(e); } }
        function rejected(value) { try { step(generator["throw"](value)); } catch (e) { reject(e); } }
        function step(result) { result.done ? resolve(result.value) : adopt(result.value).then(fulfilled, rejected); }
        step((generator = generator.apply(thisArg, _arguments || [])).next());
    });
};
Object.defineProperty(exports, "__esModule", { value: true });
const kafkajs_1 = require("kafkajs");
const client_s3_1 = require("@aws-sdk/client-s3");
const client_s3_2 = require("@aws-sdk/client-s3");
// Set the AWS Region.
const REGION = 'us-east-1'; //e.g. "us-east-1"
// Create an Amazon S3 service client object.
const s3Client = new client_s3_1.S3Client({
    region: REGION,
    endpoint: 'http://localhost:19000',
    credentials: {
        accessKeyId: 'object_storage_root_user',
        secretAccessKey: 'object_storage_root_password',
    },
    forcePathStyle: true, // Needed to work with MinIO
});
const maxChunkAge = 1000;
const maxChunkSize = 1000;
const kafka = new kafkajs_1.Kafka({
    clientId: 'ingester',
    brokers: ['localhost:9092'],
});
const consumer = kafka.consumer({
    groupId: 'session-recordings-ingestion',
});
consumer.connect();
consumer.subscribe({ topic: 'events_plugin_ingestion' });
const eventsBySessionId = {};
consumer.run({
    autoCommit: false,
    eachMessage: ({ topic, partition, message }) => __awaiter(void 0, void 0, void 0, function* () {
        // We need to parse the event to get team_id and session_id although
        // ideally we'd put this into the key instead to avoid needing to parse
        // TODO: use the key to provide routing information
        // TODO: handle concurrency properly, the access to eventsBySessionId
        // isn't threadsafe atm.
        // OPTIONAL: stream data to S3
        // OPTIONAL: use parquet to reduce reads for e.g. timerange querying
        const eventString = message.value.toString();
        const event = JSON.parse(eventString);
        let chunk = eventsBySessionId[event.properties.$session_id];
        console.log(`Processing ${event.uuid}`);
        const commitChunkToS3 = () => __awaiter(void 0, void 0, void 0, function* () {
            delete eventsBySessionId[event.properties.$session_id];
            yield s3Client.send(new client_s3_2.PutObjectCommand({
                Bucket: 'posthog',
                Key: `team_id/${chunk.team_id}/session_id/${chunk.session_id}/chunks/${chunk.oldestEventTimestamp}-${chunk.oldestOffset}`,
                Body: chunk.events.join('\n'),
            }));
            if (eventsBySessionId.length) {
                consumer.commitOffsets([
                    { topic, partition, offset: Object.values(eventsBySessionId).map(chunk => chunk.oldestOffset).sort()[0] },
                ]);
            }
        });
        if (!chunk) {
            console.log(`Creating new chunk for ${event.properties.$session_id}`);
            chunk = eventsBySessionId[event.properties.$session_id] = {
                events: [],
                size: 0,
                team_id: event.team_id,
                session_id: event.properties.$session_id,
                oldestEventTimestamp: event.timestamp,
                oldestOffset: message.offset
            };
            chunk.timer = setTimeout(() => commitChunkToS3(), maxChunkAge);
        }
        if (chunk.size + eventString.length > maxChunkSize) {
            clearTimeout(chunk.timer);
            commitChunkToS3();
            console.log(`Creating new chunk for ${event.properties.$session_id}`);
            chunk = eventsBySessionId[event.properties.$session_id] = {
                events: [],
                size: 0,
                team_id: event.team_id,
                session_id: event.properties.$session_id,
                oldestEventTimestamp: event.timestamp,
                oldestOffset: message.offset
            };
            chunk.timer = setTimeout(() => commitChunkToS3(), maxChunkAge);
        }
        chunk.events.push(eventString);
        chunk.size += eventString.length;
    }),
});
// Make sure we log any errors we haven't handled
const errorTypes = ['unhandledRejection', 'uncaughtException'];
errorTypes.map((type) => {
    process.on(type, (e) => __awaiter(void 0, void 0, void 0, function* () {
        try {
            console.log(`process.on ${type}`);
            console.error(e);
            yield consumer.disconnect();
            process.exit(0);
        }
        catch (_) {
            process.exit(1);
        }
    }));
});
// Make sure we disconnect the consumer before shutdown, especially important
// for the test use case as we'll end up having to wait for and old registered
// consumers to timeout.
const signalTraps = ['SIGTERM', 'SIGINT', 'SIGUSR2'];
signalTraps.map((type) => {
    process.once(type, () => __awaiter(void 0, void 0, void 0, function* () {
        try {
            yield consumer.disconnect();
        }
        finally {
            process.kill(process.pid, type);
        }
    }));
});
//# sourceMappingURL=ingester.js.map