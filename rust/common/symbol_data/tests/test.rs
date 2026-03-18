use posthog_symbol_data::{
    read_symbol_data, write_symbol_data, write_symbol_data_uncompressed, HermesMap,
    ProguardMapping, SourceAndMap,
};

#[test]
fn test_source_and_map_reading() {
    // This file is v1 format - validates backward compatibility
    let input = include_bytes!("static/sourcemap_with_nulls.jsdata").to_vec();
    read_symbol_data::<SourceAndMap>(input).unwrap();
}

#[test]
fn test_v2_compressed_roundtrip() {
    let input = SourceAndMap {
        minified_source: "minified_source".to_string(),
        sourcemap: "sourcemap".to_string(),
    };

    let bytes = write_symbol_data(input.clone()).unwrap();
    // Verify it's v2 (version field at offset 22)
    let version = u32::from_le_bytes(bytes[22..26].try_into().unwrap());
    assert_eq!(version, 2);
    // Verify compression byte is 1 (zstd)
    assert_eq!(bytes[30], 1);

    let output = read_symbol_data::<SourceAndMap>(bytes).unwrap();
    assert_eq!(input, output);
}

#[test]
fn test_v2_uncompressed_roundtrip() {
    let input = SourceAndMap {
        minified_source: "minified_source".to_string(),
        sourcemap: "sourcemap".to_string(),
    };

    let bytes = write_symbol_data_uncompressed(input.clone()).unwrap();
    // Verify it's v2
    let version = u32::from_le_bytes(bytes[22..26].try_into().unwrap());
    assert_eq!(version, 2);
    // Verify compression byte is 0 (none)
    assert_eq!(bytes[30], 0);

    let output = read_symbol_data::<SourceAndMap>(bytes).unwrap();
    assert_eq!(input, output);
}

#[test]
fn test_v2_compressed_hermes_map() {
    let input = HermesMap {
        sourcemap: "hermes map data".to_string(),
    };

    let bytes = write_symbol_data(input.clone()).unwrap();
    let output = read_symbol_data::<HermesMap>(bytes).unwrap();
    assert_eq!(input, output);
}

#[test]
fn test_v2_compressed_proguard_mapping() {
    let input = ProguardMapping {
        content: "proguard mapping data".to_string(),
    };

    let bytes = write_symbol_data(input.clone()).unwrap();
    let output = read_symbol_data::<ProguardMapping>(bytes).unwrap();
    assert_eq!(input, output);
}

#[test]
fn test_v2_compressed_large_payload() {
    // Verify compression works well on large, repetitive data
    let large_source = "a".repeat(100_000);
    let large_map = "b".repeat(100_000);
    let input = SourceAndMap {
        minified_source: large_source,
        sourcemap: large_map,
    };

    let bytes = write_symbol_data(input.clone()).unwrap();
    // Compressed output should be significantly smaller than uncompressed
    let uncompressed_bytes = write_symbol_data_uncompressed(input.clone()).unwrap();
    assert!(bytes.len() < uncompressed_bytes.len() / 2);

    let output = read_symbol_data::<SourceAndMap>(bytes).unwrap();
    assert_eq!(input, output);
}
