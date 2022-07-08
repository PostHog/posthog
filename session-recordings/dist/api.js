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
var __importDefault = (this && this.__importDefault) || function (mod) {
    return (mod && mod.__esModule) ? mod : { "default": mod };
};
Object.defineProperty(exports, "__esModule", { value: true });
const express_1 = __importDefault(require("express"));
const express_2 = require("express");
const consumers_1 = __importDefault(require("stream/consumers"));
const client_s3_1 = require("@aws-sdk/client-s3");
const client_s3_2 = require("@aws-sdk/client-s3");
// Set the AWS Region.
const REGION = "us-east-1"; //e.g. "us-east-1"
// Create an Amazon S3 service client object.
const s3Client = new client_s3_1.S3Client({
    region: REGION, endpoint: "http://localhost:19000",
    credentials: {
        accessKeyId: 'object_storage_root_user',
        secretAccessKey: 'object_storage_root_password',
    },
    forcePathStyle: true, // Needed to work with MinIO
});
const routes = (0, express_2.Router)();
routes.get('/api/team/:teamId/session_recordings/:sessionId', ({ params: { teamId, sessionId } }, res) => __awaiter(void 0, void 0, void 0, function* () {
    var _a;
    // Fetch events for the specified session recording
    // TODO: habdle time range querying
    const listResponse = yield s3Client.send(new client_s3_2.ListObjectsCommand({
        Bucket: "posthog",
        Prefix: `team_id/${teamId}/session_id/${sessionId}/chunks/`,
    }));
    const objects = yield Promise.all(((_a = listResponse.Contents) === null || _a === void 0 ? void 0 : _a.map(key => s3Client.send(new client_s3_2.GetObjectCommand({
        Bucket: "posthog",
        Key: key.Key
    })))) || []);
    const blobs = yield Promise.all(objects.map(object => consumers_1.default.text(object.Body)));
    // TODO: we probably don't need to parse JSON here if we're careful and
    // construct the JSON progressively
    const events = blobs.flatMap(blob => blob.split("\n").map(line => JSON.parse(line)));
    return res.json({ events });
}));
const server = (0, express_1.default)();
server.use(routes);
server.listen(3000);
//# sourceMappingURL=api.js.map