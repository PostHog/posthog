use anyhow::Result;

fn main() -> Result<()> {
    let proto_file = "proto/kafka_producer.proto";
    let proto_dir = "proto";

    tonic_build::configure()
        .build_server(true)
        .build_client(true)
        .out_dir("./src/proto")
        .compile_protos(&[proto_file], &[proto_dir])?;

    Ok(())
}
