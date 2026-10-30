"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.convertToInternalPoolConfig = convertToInternalPoolConfig;
exports.serializeObject = serializeObject;
exports.deserializeObject = deserializeObject;
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
function serializeObject(name, obj) {
    if (obj === null) {
        return null;
    }
    else if (typeof obj === 'object' && obj !== null) {
        return JSON.stringify(obj);
    }
    throw new Error(`${name} must be either an object or null`);
}
function deserializeObject(name, str) {
    if (str === null) {
        return null;
    }
    else if (typeof str === 'string') {
        return JSON.parse(str);
    }
    throw new Error(`${name} must be either a string or null`);
}
//# sourceMappingURL=helpers.js.map