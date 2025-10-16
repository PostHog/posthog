use crate::{error::Error, utils::assert_at_least_as_long_as};

const MAGIC: &[u8] = b"posthog_error_tracking";
const VERSION: u32 = 1;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum SymbolDataType {
    SourceAndMap = 2,
    HermesMap = 3,
    ProguardMapping = 4,
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
    let d_type = T::data_type();
    let bytes = data.into_bytes();
    let mut buffer = Vec::with_capacity(header_len() + bytes.len());
    buffer.extend_from_slice(MAGIC);
    buffer.extend_from_slice(&VERSION.to_le_bytes());
    buffer.extend_from_slice(&(d_type as u32).to_le_bytes());
    buffer.extend_from_slice(&bytes);
    Ok(buffer)
}

pub fn read_as<T>(data: Vec<u8>) -> Result<T, Error>
where
    T: SymbolData,
{
    assert_at_least_as_long_as(header_len(), data.len())?;
    assert_has_magic(&data)?;
    assert_version(&data)?;
    assert_data_type(&data, T::data_type())?;
    T::from_bytes(data[header_len()..].to_vec())
}

pub fn assert_version(buffer: &[u8]) -> Result<(), Error> {
    let version = u32::from_le_bytes(buffer[MAGIC.len()..MAGIC.len() + 4].try_into().unwrap());
    if version > VERSION {
        return Err(Error::WrongVersion(version, VERSION));
    }
    Ok(())
}

fn assert_has_magic(buffer: &[u8]) -> Result<(), Error> {
    if &buffer[..MAGIC.len()] != MAGIC {
        return Err(Error::InvalidMagic);
    }
    Ok(())
}

pub fn assert_data_type(buffer: &[u8], expected_type: SymbolDataType) -> Result<(), Error> {
    let data_type = u32::from_le_bytes(buffer[header_len() - 4..header_len()].try_into().unwrap());
    if data_type != expected_type as u32 {
        Err(Error::InvalidDataType(
            data_type,
            format!("{expected_type:?}"),
        ))
    } else {
        Ok(())
    }
}

const fn header_len() -> usize {
    // Magic + Version + Type
    MAGIC.len() + VERSION.to_le_bytes().len() + std::mem::size_of::<u32>()
}
