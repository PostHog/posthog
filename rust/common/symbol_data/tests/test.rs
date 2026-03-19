use posthog_symbol_data::{
    read_symbol_data, write_symbol_data, write_symbol_data_uncompressed, HermesMap,
    ProguardMapping, SourceAndMap,
};

const MAGIC_LEN: usize = b"posthog_error_tracking".len();
const VERSION_OFFSET: usize = MAGIC_LEN;
const COMPRESSION_OFFSET: usize = MAGIC_LEN + 4 + 4; // after MAGIC + VERSION + TYPE

#[test]
fn test_source_and_map_reading() {
    // This file is v1 format - validates backward compatibility
    let input = include_bytes!("static/sourcemap_with_nulls.jsdata").to_vec();
    read_symbol_data::<SourceAndMap>(input).unwrap();
}

#[test]
fn test_v2_compressed_header() {
    let input = SourceAndMap {
        minified_source: "minified_source".to_string(),
        sourcemap: "sourcemap".to_string(),
    };

    let bytes = write_symbol_data(input.clone()).unwrap();
    let version = u32::from_le_bytes(
        bytes[VERSION_OFFSET..VERSION_OFFSET + 4]
            .try_into()
            .unwrap(),
    );
    assert_eq!(version, 2);
    assert_eq!(bytes[COMPRESSION_OFFSET], 1); // zstd

    let output = read_symbol_data::<SourceAndMap>(bytes).unwrap();
    assert_eq!(input, output);
}

#[test]
fn test_v2_uncompressed_header() {
    let input = SourceAndMap {
        minified_source: "minified_source".to_string(),
        sourcemap: "sourcemap".to_string(),
    };

    let bytes = write_symbol_data_uncompressed(input.clone()).unwrap();
    let version = u32::from_le_bytes(
        bytes[VERSION_OFFSET..VERSION_OFFSET + 4]
            .try_into()
            .unwrap(),
    );
    assert_eq!(version, 2);
    assert_eq!(bytes[COMPRESSION_OFFSET], 0); // none

    let output = read_symbol_data::<SourceAndMap>(bytes).unwrap();
    assert_eq!(input, output);
}

macro_rules! roundtrip_test {
    ($name:ident, $ty:ty, $value:expr) => {
        #[test]
        fn $name() {
            let input = $value;
            let bytes = write_symbol_data(input.clone()).unwrap();
            let output = read_symbol_data::<$ty>(bytes).unwrap();
            assert_eq!(input, output);
        }
    };
}

roundtrip_test!(
    test_v2_roundtrip_source_and_map,
    SourceAndMap,
    SourceAndMap {
        minified_source: "minified_source".to_string(),
        sourcemap: "sourcemap".to_string(),
    }
);
roundtrip_test!(
    test_v2_roundtrip_hermes_map,
    HermesMap,
    HermesMap {
        sourcemap: "hermes map data".to_string(),
    }
);
roundtrip_test!(
    test_v2_roundtrip_proguard_mapping,
    ProguardMapping,
    ProguardMapping {
        content: "proguard mapping data".to_string(),
    }
);

#[test]
fn test_v2_compressed_large_payload() {
    let large_source = "a".repeat(100_000);
    let large_map = "b".repeat(100_000);
    let input = SourceAndMap {
        minified_source: large_source,
        sourcemap: large_map,
    };

    let bytes = write_symbol_data(input.clone()).unwrap();
    let uncompressed_bytes = write_symbol_data_uncompressed(input.clone()).unwrap();
    assert!(bytes.len() < uncompressed_bytes.len() / 2);

    let output = read_symbol_data::<SourceAndMap>(bytes).unwrap();
    assert_eq!(input, output);
}
