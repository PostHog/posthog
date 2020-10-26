const cache = {}

export function createCache() {
    return {
        set: function (key, value) {
            cache[key] = value
        },
        get: function (key, defaultValue) {
            if (typeof cache[key] === 'undefined') {
                return defaultValue
            }
            return cache[key]
        },
    }
}
