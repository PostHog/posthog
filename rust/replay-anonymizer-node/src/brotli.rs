use brotlic::{CompressionMode, Quality, WindowSize};

/// Node's zlib default window, so the output matches `zlib.brotliCompress` byte for byte.
const WINDOW_BITS: u8 = 22;

pub fn compress(input: &[u8], quality: u8) -> Result<Vec<u8>, String> {
    let invalid_quality = || format!("brotli quality must be from 2 to 11, got {quality}");
    let quality = Quality::new(quality).map_err(|_| invalid_quality())?;
    let max_compressed_size =
        brotlic::compress_bound(input.len(), quality).ok_or_else(invalid_quality)?;

    let mut output = vec![0u8; max_compressed_size];
    let written = brotlic::compress(
        input,
        &mut output,
        quality,
        WindowSize::new(WINDOW_BITS).expect("22 is a valid brotli window"),
        CompressionMode::Generic,
    )
    .map_err(|error| format!("brotli compression failed: {error}"))?;
    output.truncate(written);
    output.shrink_to_fit();
    Ok(output)
}

#[cfg(test)]
mod tests {
    use std::io::Read;

    use super::*;

    #[test]
    fn incompressible_input_round_trips() {
        let mut state = 0x9E37_79B9_7F4A_7C15u64;
        let incompressible: Vec<u8> = (0..200_000)
            .map(|_| {
                state ^= state << 13;
                state ^= state >> 7;
                state ^= state << 17;
                (state >> 56) as u8
            })
            .collect();
        let compressed = compress(&incompressible, 9).unwrap();

        let mut decoded = Vec::new();
        brotlic::DecompressorReader::new(compressed.as_slice())
            .read_to_end(&mut decoded)
            .unwrap();
        assert_eq!(decoded, incompressible);
    }
}
