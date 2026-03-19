use std::io::{Cursor, Read as _, Write as _};

use crate::{error::Error, utils::assert_at_least_as_long_as};

const MAGIC: &[u8] = b"posthog_error_tracking";
const VERSION: u32 = 2;
const V1_VERSION: u32 = 1;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum SymbolDataType {
    SourceAndMap = 2,
    HermesMap = 3,
    ProguardMapping = 4,
    AppleDsym = 5,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
#[repr(u8)]
pub enum Compression {
    None = 0,
    Zstd = 1,
}

impl TryFrom<u8> for Compression {
    type Error = Error;

    fn try_from(value: u8) -> Result<Self, Self::Error> {
        match value {
            0 => Ok(Compression::None),
            1 => Ok(Compression::Zstd),
            other => Err(Error::UnknownCompression(other)),
        }
    }
}

pub trait SymbolData: Sized {
    fn from_bytes(data: Vec<u8>) -> Result<Self, Error>;
    fn into_bytes(self) -> Vec<u8>;
    fn data_type() -> SymbolDataType;
}

pub fn write<T>(data: T) -> Result<Vec<u8>, Error>
where
    T: SymbolData,
{
    write_inner(data, Compression::Zstd)
}

pub fn write_uncompressed<T>(data: T) -> Result<Vec<u8>, Error>
where
    T: SymbolData,
{
    write_inner(data, Compression::None)
}

fn write_inner<T>(data: T, compression: Compression) -> Result<Vec<u8>, Error>
where
    T: SymbolData,
{
    let d_type = T::data_type();
    let raw_bytes = data.into_bytes();

    let payload = match compression {
        Compression::None => raw_bytes,
        Compression::Zstd => {
            let mut encoder = zstd::Encoder::new(Vec::new(), 3)
                .map_err(|e| Error::CompressionError(e.to_string()))?;
            encoder
                .write_all(&raw_bytes)
                .map_err(|e| Error::CompressionError(e.to_string()))?;
            encoder
                .finish()
                .map_err(|e| Error::CompressionError(e.to_string()))?
        }
    };

    let mut buffer = Vec::with_capacity(v2_header_len() + payload.len());
    buffer.extend_from_slice(MAGIC);
    buffer.extend_from_slice(&VERSION.to_le_bytes());
    buffer.extend_from_slice(&(d_type as u32).to_le_bytes());
    buffer.push(compression as u8);
    buffer.extend_from_slice(&payload);
    Ok(buffer)
}

pub fn read_as<T>(data: Vec<u8>) -> Result<T, Error>
where
    T: SymbolData,
{
    let version = read_version(&data)?;

    match version {
        V1_VERSION => {
            assert_at_least_as_long_as(v1_header_len(), data.len())?;
            assert_data_type_impl(&data, T::data_type())?;
            T::from_bytes(data[v1_header_len()..].to_vec())
        }
        VERSION => {
            assert_at_least_as_long_as(v2_header_len(), data.len())?;
            assert_data_type_impl(&data, T::data_type())?;
            let compression = Compression::try_from(data[v2_header_len() - 1])?;
            let payload = &data[v2_header_len()..];
            let decompressed = match compression {
                Compression::None => payload.to_vec(),
                Compression::Zstd => {
                    let mut decoder = zstd::Decoder::new(Cursor::new(payload))
                        .map_err(|e| Error::CompressionError(e.to_string()))?;
                    let mut out = Vec::new();
                    decoder
                        .read_to_end(&mut out)
                        .map_err(|e| Error::CompressionError(e.to_string()))?;
                    out
                }
            };
            T::from_bytes(decompressed)
        }
        other => Err(Error::WrongVersion(other, VERSION)),
    }
}

fn read_version(buffer: &[u8]) -> Result<u32, Error> {
    assert_at_least_as_long_as(MAGIC.len() + 4, buffer.len())?;
    assert_has_magic(buffer)?;
    Ok(u32::from_le_bytes(
        buffer[MAGIC.len()..MAGIC.len() + 4].try_into().unwrap(),
    ))
}

fn assert_has_magic(buffer: &[u8]) -> Result<(), Error> {
    if &buffer[..MAGIC.len()] != MAGIC {
        return Err(Error::InvalidMagic);
    }
    Ok(())
}

fn assert_data_type_impl(buffer: &[u8], expected_type: SymbolDataType) -> Result<(), Error> {
    // Type field sits at the same offset in both v1 and v2 (after MAGIC + VERSION)
    let type_offset = MAGIC.len() + 4;
    let data_type = u32::from_le_bytes(buffer[type_offset..type_offset + 4].try_into().unwrap());
    if data_type != expected_type as u32 {
        Err(Error::InvalidDataType(
            data_type,
            format!("{expected_type:?}"),
        ))
    } else {
        Ok(())
    }
}

const fn v1_header_len() -> usize {
    // Magic + Version + Type
    MAGIC.len() + 4 + 4
}

const fn v2_header_len() -> usize {
    // Magic + Version + Type + Compression
    MAGIC.len() + 4 + 4 + 1
}
