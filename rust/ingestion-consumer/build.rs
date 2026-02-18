fn main() -> Result<(), Box<dyn std::error::Error>> {
    let proto_root = std::env::var("PROTO_ROOT").unwrap_or_else(|_| "../../proto".to_string());

    tonic_build::configure()
        .build_server(false)
        .build_client(true)
        .compile_protos(
            &[format!("{proto_root}/ingestion/v1/ingestion.proto")],
            &[proto_root],
        )?;
    Ok(())
}
