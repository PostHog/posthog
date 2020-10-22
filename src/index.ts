const grpc = require('grpc')
import { struct } from 'pb-util'
import { setupPlugins, runPlugins } from './plugins'
const protoLoader = require('@grpc/proto-loader')
require('google-protobuf/google/protobuf/struct_pb')
const packageDefinition = protoLoader.loadSync('./plugins.proto', {
    keepCase: true,
    longs: Number,
    enums: String,
    objects: true,
    defaults: true,
    oneofs: true,
})
const { PluginService } = grpc.loadPackageDefinition(packageDefinition)

const server = new grpc.Server()
server.addService(PluginService.service, {
    OnCapture: async (call, callback) => {
        const { event } = call.request
        const processedEvent = await runPlugins({ ...event, properties: struct.decode(event.properties) })
        const eventResponse = { ...processedEvent, properties: struct.encode(processedEvent.properties) }
        callback(null, { event: eventResponse })
    },
})

setupPlugins()

server.bind('127.0.0.1:50051', grpc.ServerCredentials.createInsecure())
console.log('Server running at http://127.0.0.1:50051')
server.start()
