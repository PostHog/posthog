use anyhow::Result;

fn main() -> Result<()> {
    // Skip proto generation in CI or when SKIP_PROTO_BUILD is set
    if std::env::var("CI").is_ok() || std::env::var("SKIP_PROTO_BUILD").is_ok() {
        println!("cargo:warning=Skipping proto generation (using checked-in files)");
        return Ok(());
    }

    let proto_file = "proto/kafka_producer.proto";
    let proto_dir = "proto";

    tonic_build::configure()
        .build_server(true)
        .build_client(true)
        .out_dir("./src/proto")
        .protoc_arg("--experimental_allow_proto3_optional")
        .compile_protos(&[proto_file], &[proto_dir])?;

    Ok(())
}
