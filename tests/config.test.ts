import { getDefaultConfig, overrideWithEnv } from '../src/config'

test('overrideWithEnv 1', async () => {
    const defaultConfig = getDefaultConfig()
    const env = {
        DISABLE_WEB: 'false',
        WEB_PORT: '3008',
        WEB_HOSTNAME: '0.0.0.0',
        BASE_DIR: undefined,
    }
    const config = overrideWithEnv(getDefaultConfig(), env)

    expect(config.DISABLE_WEB).toEqual(false)
    expect(config.WEB_PORT).toEqual(3008)
    expect(config.WEB_HOSTNAME).toEqual('0.0.0.0')
    expect(config.BASE_DIR).toEqual(defaultConfig.BASE_DIR)
})

test('overrideWithEnv 2', async () => {
    const defaultConfig = getDefaultConfig()
    const env = {
        DISABLE_WEB: '1',
        WEB_PORT: '3008.12',
    }
    const config = overrideWithEnv(getDefaultConfig(), env)

    expect(config.DISABLE_WEB).toEqual(true)
    expect(config.WEB_PORT).toEqual(3008.12)
})
