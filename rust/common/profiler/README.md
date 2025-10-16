## Profiling Rust services with pprof

This package aims to help Rust workspace services with an [Axum web server](https://docs.rs/axum/latest/axum/) create CPU and heap profile snapshots and visualizations that you can download and interact with on your local machine.

The core output format and tooling for all of the above is [pprof](https://github.com/google/pprof). Most of the reference material and usage for `pprof` is Golang oriented, but translates pretty naturally to the Rust environment.

### Setup

#### Local machine setup

1. Install a recent version of Golang (this will include the core `pprof` tool)
2. Install related local dependencies for desired visualization features (`graphviz`, `dot` etc.)
3. Install `kubectl` and ensure AWS credentials/SSO are configured to use it against our production k8s clusters

#### Service setup

This library can be integrated into your Rust workspace project in a couple steps:

1. Add the `common/profiler` dependency to your service. **Replace `common/alloc` dependency if present**
2. Add the `used_with_profiling!()` macro to your `main.rs`, or replace `common/alloc`'s `used!()` invocation - [example here](https://github.com/PostHog/posthog/blob/b76f90ce684d8ff955074ae19d5d8ef49f4181ca/rust/kafka-deduplicator/src/main.rs#L26) as [defined here](https://github.com/PostHog/posthog/blob/b76f90ce684d8ff955074ae19d5d8ef49f4181ca/rust/common/profiler/src/lib.rs#L13-L22)
3. Add the profiling trigger endpoints to your Axum server's `Router` - [example here](https://github.com/PostHog/posthog/blob/b76f90ce684d8ff955074ae19d5d8ef49f4181ca/rust/kafka-deduplicator/src/main.rs#L129-L133) as [defined here](https://github.com/PostHog/posthog/blob/b76f90ce684d8ff955074ae19d5d8ef49f4181ca/rust/common/profiler/src/router.rs#L8-L14)

...and that's about it! Deploy your service and use the instructions below to get started

### Using pprof in production

#### Obtaining a profile snapshot

Set up k8s port forwarding on your local machine from your service's load balancer or a particular pod. Note this is a **blocking operation** - you can background it, or leave it running in foreground and start a new session for next steps.

```bash
# Set local k8s env (posthog-prod, posthog-prod-eu, dev)
$ kubectl config use-context posthog-prod-eu

# Notes:
# - You can also use "pod/kafka-deduplicator-2" (pod name) to select a specific pod
# - Ensure you forward the HTTP port that your Axum server exposes in k8s
$ kubectl port-forward --namespace posthog service/kafka-deduplicator 8000:8000
```

`curl` the pprof endpoint and pipe the resulting GZIP'd output to your local filesystem.

```bash
# Capture CPU profile report as GZIP'd protobuf file. Optional URL query params:
#     seconds=N    | How long the sampling profiler should run before returning the report (default 10)
#     frequency=N  | Sampling frequency for profile report (default 200)
#
# Note: The defaults are a good place to start. Ensure "seconds" param doesn't exceed the request timeout!
$ curl -sSL -H 'Connection: keep-alive' -H 'Keep-Alive: timeout=60,max=100' 'http://localhost:8000/pprof/profile/report' > profile.pb.gz

# Obtain a heap allocation profile
$ curl -sSL -H 'Connection: keep-alive' -H 'Keep-Alive: timeout=60,max=100' 'http://localhost:8000/pprof/heap/report' > heap.pb.gz

# Corresponding profile and heap flamegraph endpoints return pre-generated SVG images of configurable size
```

Introspect on the profile reports you've pulled down

```bash
# Unzip the report protobuf
$ unzip profile.pb.gz
# Use pprof tool to introspect on report. Basic syntax:
$ go tool pprof <options> <optional_path_to_local_debug_binary> <path_to_profile_report_file>

# Examples:

# Open interactive web interface to analyze report (recommended)
$ go tool pprof -http=localhost:<PORT> profile.pb

# Open interactive CLI shell with report
$ go tool pprof profile.pb

# Include service binary for additional symbol translation (YMMV, can add this arg to any of the commands listed here)
$ go tool pprof posthog/rust/target/debug/kafka-deduplicator profile.pb

# Open web browser with SVG image of profile report
$ go tool pprof -web profile.pb
# Generate and open a local PNG image of the profile report
$ go tool pprof -png profile.pb && open profile001.png
# Quick summary report
$ go tool pprof -top profile.pb
```

Additional introspect options and context on `pprof` is available online:

* [General pprof intro](https://jvns.ca/blog/2017/09/24/profiling-go-with-pprof/)
* [go tool pprof options](https://github.com/google/pprof/tree/main/doc#options)
* [Web interface intro](https://github.com/google/pprof/tree/main/doc#web-interface-1)
* [Interpret a pprof profile PNG](https://github.com/google/pprof/blob/main/doc/README.md#interpreting-the-callgraph)
* [Heap profiler and flamegraph details](https://www.polarsignals.com/blog/posts/2023/12/20/rust-memory-profiling)
* [Symbolization details](https://github.com/google/pprof/tree/main/doc#symbolization)
