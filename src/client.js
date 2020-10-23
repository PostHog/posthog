const grpc = require('grpc')
const protoLoader = require('@grpc/proto-loader')
require('google-protobuf/google/protobuf/struct_pb')

const packageDefinition = protoLoader.loadSync('../protos/posthog/grpc/plugins.proto', {
    keepCase: true,
    longs: Number,
    enums: String,
    defaults: true,
    objects: true,
    oneofs: true,
})
const { PluginService } = grpc.loadPackageDefinition(packageDefinition)

module.exports = { client: new PluginService('localhost:50051', grpc.credentials.createInsecure()) }
