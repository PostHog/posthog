"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.deserializeObject = exports.serializeObject = exports.convertToInternalPoolConfig = void 0;
function convertToInternalPoolConfig(poolConfig) {
    return {
        db_url: poolConfig.dbUrl,
        max_connections: poolConfig.maxConnections,
        min_connections: poolConfig.minConnections,
        acquire_timeout_seconds: poolConfig.acquireTimeoutSeconds,
        max_lifetime_seconds: poolConfig.maxLifetimeSeconds,
        idle_timeout_seconds: poolConfig.idleTimeoutSeconds,
    };
}
exports.convertToInternalPoolConfig = convertToInternalPoolConfig;
function serializeObject(name, obj) {
    if (obj === null) {
        return null;
    }
    else if (typeof obj === 'object' && obj !== null) {
        return JSON.stringify(obj);
    }
    throw new Error(`${name} must be either an object or null`);
}
exports.serializeObject = serializeObject;
function deserializeObject(name, str) {
    if (str === null) {
        return null;
    }
    else if (typeof str === 'string') {
        return JSON.parse(str);
    }
    throw new Error(`${name} must be either a string or null`);
}
exports.deserializeObject = deserializeObject;
//# sourceMappingURL=helpers.js.map