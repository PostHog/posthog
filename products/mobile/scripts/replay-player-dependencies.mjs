export function mobileReplayDependencies(app) {
    return {
        name: 'mobile-replay-dependencies',
        setup(build) {
            build.onResolve({ filter: /^(?:posthog-js(?:\/|$)|fflate$|fzstd$|hls\.js$|p-limit$)/ }, (args) => {
                if (args.pluginData?.mobileReplayDependency) return
                return build.resolve(args.path, {
                    resolveDir: app,
                    kind: args.kind,
                    pluginData: { mobileReplayDependency: true },
                })
            })
        },
    }
}
