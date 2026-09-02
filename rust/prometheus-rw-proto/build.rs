fn main() -> Result<(), Box<dyn std::error::Error>> {
    let proto_root = std::env::var("PROTO_ROOT").unwrap_or_else(|_| "../../proto".to_string());

    // Messages only — no gRPC service in this proto, so skip server/client codegen.
    tonic_build::configure()
        .build_server(false)
        .build_client(false)
        .compile_protos(
            &[format!("{proto_root}/prometheus/v1/remote_write.proto")],
            &[proto_root],
        )?;
    Ok(())
}
