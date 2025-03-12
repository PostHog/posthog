# Clickhouse UDFs

## Development workflow

-   Building the binaries:
    -   Switch to the udfs directory `cd udfs`
    -   Execute the build script: `./udfs/build.sh`

## Deployment workflow

At the moment we don't have a pipeline to deploy a new version of a UDF. As such, we manually split the deployment into four steps:

1. Deploying the binary file of the function.
2. Deploying a ClickHouse configuration change to use the function.
3. Checking in Metabase if the function was picked up by ClickHouse.
4. Deploying the code change that uses the new function.

## Design decisions

-   We tried writing the UDFs in Python, but this cause ClickHouse nodes to crash as the garbage collector could not keep up. As such we're now writing the functions in Rust.
-   We're using `cross-rs` to compile the binaries - it's a cross platfrom rust compiler.

## Troubleshooting

### Running `./udfs/build.sh` fails in flox environment

If you're using `flox` for development, you'll have to exit out of the environment first (nix os isn't supported).

```
Error:
   0: could not determine os in target triplet
   1: unsupported os in target, abi: "1.82.0", system: "rustc"
```
