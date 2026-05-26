fn main() -> Result<(), Box<dyn std::error::Error>> {
    let proto_root = std::env::var("PROTO_ROOT").unwrap_or_else(|_| "proto".to_string());

    println!("cargo:rerun-if-changed={proto_root}/cymbal/v1/pipeline.proto");
    println!("cargo:rerun-if-changed={proto_root}/cymbal/v1/stage.proto");

    tonic_build::configure()
        .build_server(true)
        .build_client(true)
        .compile_protos(
            &[
                format!("{proto_root}/cymbal/v1/pipeline.proto"),
                format!("{proto_root}/cymbal/v1/stage.proto"),
            ],
            &[proto_root],
        )?;

    Ok(())
}
