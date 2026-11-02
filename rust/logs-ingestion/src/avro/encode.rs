//! Container encoding laid out as avsc's `BlockEncoder` lays it out.

use std::cell::RefCell;

use rand::RngCore;

use super::schema::Schema;
use super::value::AvroValue;
use super::{AvroError, MAGIC};

/// avsc's default block size, in bytes of serialized records before compression.
const BLOCK_SIZE: usize = 65_536;

pub(crate) fn write_long(out: &mut Vec<u8>, n: i64) {
    let mut z = ((n << 1) ^ (n >> 63)) as u64;
    loop {
        if z & !0x7f == 0 {
            out.push(z as u8);
            return;
        }
        out.push(((z & 0x7f) | 0x80) as u8);
        z >>= 7;
    }
}

fn write_bytes(out: &mut Vec<u8>, b: &[u8]) {
    write_long(out, b.len() as i64);
    out.extend_from_slice(b);
}

fn invalid(schema: &Schema, value: &AvroValue) -> AvroError {
    AvroError::Encode(format!("invalid {}: {:?}", schema.short_name(), value))
}

fn is_safe_long(n: i64) -> bool {
    (-9_007_199_254_740_990..=9_007_199_254_740_990).contains(&n)
}

/// The union branch avsc picks for a value: by the value's JavaScript type.
fn union_branch<'s>(branches: &'s [Schema], value: &AvroValue) -> Option<(usize, &'s Schema)> {
    branches.iter().enumerate().find(|(_, b)| {
        matches!(
            (b, value),
            (Schema::Null, AvroValue::Null)
                | (Schema::Boolean, AvroValue::Boolean(_))
                | (
                    Schema::Int | Schema::Long | Schema::Float | Schema::Double,
                    AvroValue::Int(_)
                        | AvroValue::Long(_)
                        | AvroValue::Float(_)
                        | AvroValue::Double(_)
                )
                | (
                    Schema::Bytes | Schema::Fixed(_),
                    AvroValue::Bytes(_) | AvroValue::Fixed(_)
                )
                | (
                    Schema::String | Schema::Enum(_),
                    AvroValue::String(_) | AvroValue::Enum(_)
                )
                | (Schema::Array(_), AvroValue::Array(_))
                | (Schema::Map(_), AvroValue::Map(_))
                | (Schema::Record(_), AvroValue::Record(_))
        )
    })
}

fn as_number(value: &AvroValue) -> Option<f64> {
    match value {
        AvroValue::Int(n) | AvroValue::Long(n) => Some(*n as f64),
        AvroValue::Float(f) | AvroValue::Double(f) => Some(*f),
        _ => None,
    }
}

pub(crate) fn write_value(
    out: &mut Vec<u8>,
    schema: &Schema,
    value: &AvroValue,
) -> Result<(), AvroError> {
    match schema {
        Schema::Null => {
            if !value.is_null() {
                return Err(invalid(schema, value));
            }
        }
        Schema::Boolean => match value {
            AvroValue::Boolean(b) => out.push(*b as u8),
            _ => return Err(invalid(schema, value)),
        },
        Schema::Int => match as_number(value) {
            Some(n) if n.fract() == 0.0 && (i32::MIN as f64..=i32::MAX as f64).contains(&n) => {
                write_long(out, n as i64)
            }
            _ => return Err(invalid(schema, value)),
        },
        Schema::Long => match as_number(value) {
            Some(n) if n.fract() == 0.0 && is_safe_long(n as i64) => write_long(out, n as i64),
            _ => return Err(invalid(schema, value)),
        },
        Schema::Float => match as_number(value) {
            Some(n) => out.extend_from_slice(&(n as f32).to_le_bytes()),
            None => return Err(invalid(schema, value)),
        },
        Schema::Double => match as_number(value) {
            Some(n) => out.extend_from_slice(&n.to_le_bytes()),
            None => return Err(invalid(schema, value)),
        },
        Schema::Bytes => match value.as_bytes() {
            Some(b) => write_bytes(out, b),
            None => return Err(invalid(schema, value)),
        },
        Schema::String => match value {
            AvroValue::String(s) => write_bytes(out, s.as_bytes()),
            _ => return Err(invalid(schema, value)),
        },
        Schema::Fixed(f) => match value.as_bytes() {
            Some(b) if b.len() == f.size => out.extend_from_slice(b),
            _ => return Err(invalid(schema, value)),
        },
        Schema::Enum(e) => {
            let symbol = match value {
                AvroValue::Enum(s) | AvroValue::String(s) => s,
                _ => return Err(invalid(schema, value)),
            };
            match e.symbols.iter().position(|s| s == symbol) {
                Some(i) => write_long(out, i as i64),
                None => return Err(invalid(schema, value)),
            }
        }
        Schema::Union(branches) => match union_branch(branches, value) {
            Some((index, branch)) => {
                write_long(out, index as i64);
                write_value(out, branch, value)?;
            }
            None => return Err(invalid(schema, value)),
        },
        Schema::Array(items) => match value {
            AvroValue::Array(values) => {
                if !values.is_empty() {
                    write_long(out, values.len() as i64);
                    for v in values {
                        write_value(out, items, v)?;
                    }
                }
                out.push(0);
            }
            _ => return Err(invalid(schema, value)),
        },
        Schema::Map(values) => match value {
            AvroValue::Map(map) => {
                if !map.is_empty() {
                    write_long(out, map.len() as i64);
                    for (k, v) in map.iter() {
                        write_bytes(out, k.as_bytes());
                        write_value(out, values, v)?;
                    }
                }
                out.push(0);
            }
            _ => return Err(invalid(schema, value)),
        },
        Schema::Record(record) => match value {
            AvroValue::Record(fields) => {
                // A decoded record holds the schema's fields in schema order, so each lookup
                // first tries the same position. With unique names, a match there while every
                // earlier position matched is also the first field of that name.
                let mut aligned = record.field_index.len() == record.fields.len();
                for (i, field) in record.fields.iter().enumerate() {
                    let positional = match fields.get(i) {
                        Some((name, v)) if aligned && name == &field.name => Some(v),
                        _ => None,
                    };
                    // A field the value lacks encodes as `undefined`, which a nullable union
                    // writes as null, as avsc does.
                    let v = match positional {
                        Some(v) => v,
                        None => {
                            aligned = false;
                            fields
                                .iter()
                                .find(|(name, _)| *name == field.name)
                                .map(|(_, v)| v)
                                .unwrap_or(&AvroValue::Null)
                        }
                    };
                    write_value(out, &field.schema, v)?;
                }
            }
            _ => return Err(invalid(schema, value)),
        },
    }
    Ok(())
}

thread_local! {
    /// A zstd context is large to set up, so each thread keeps one at level 1.
    static COMPRESSOR: RefCell<Option<zstd::bulk::Compressor<'static>>> = const { RefCell::new(None) };
}

fn zstd_compress(data: &[u8]) -> std::io::Result<Vec<u8>> {
    COMPRESSOR.with(|cell| {
        let mut slot = cell.borrow_mut();
        let compressor = match slot.as_mut() {
            Some(c) => c,
            None => slot.insert(zstd::bulk::Compressor::new(1)?),
        };
        compressor.compress(data)
    })
}

fn compress(codec: &str, data: &[u8]) -> Result<Vec<u8>, AvroError> {
    match codec {
        "zstandard" => zstd_compress(data).map_err(|_| AvroError::Decompression(codec.to_string())),
        "null" => Ok(data.to_vec()),
        other => Err(AvroError::UnknownCodec(other.to_string())),
    }
}

/// `encodeLogRecords`: a header with avsc's schema JSON, then records in blocks of at most
/// 64 KiB of serialized data. A record larger than the block size gets a block of its own and
/// doubles the block size, as in avsc.
pub fn encode_container(
    schema: &Schema,
    codec: &str,
    records: &[AvroValue],
) -> Result<Vec<u8>, AvroError> {
    let mut sync = [0u8; 16];
    rand::thread_rng().fill_bytes(&mut sync);

    let mut out = Vec::new();
    out.extend_from_slice(&MAGIC);
    write_long(&mut out, 2);
    write_bytes(&mut out, b"avro.schema");
    write_bytes(&mut out, schema.avsc_json_str().as_bytes());
    write_bytes(&mut out, b"avro.codec");
    write_bytes(&mut out, codec.as_bytes());
    out.push(0);
    out.extend_from_slice(&sync);

    let mut block_size = BLOCK_SIZE;
    let mut block = Vec::new();
    let mut count = 0i64;
    let mut record = Vec::new();
    let flush =
        |out: &mut Vec<u8>, block: &mut Vec<u8>, count: &mut i64| -> Result<(), AvroError> {
            let compressed = compress(codec, block)?;
            write_long(out, *count);
            write_bytes(out, &compressed);
            out.extend_from_slice(&sync);
            block.clear();
            *count = 0;
            Ok(())
        };
    for value in records {
        record.clear();
        write_value(&mut record, schema, value)?;
        if block.len() + record.len() > block_size {
            if !block.is_empty() {
                flush(&mut out, &mut block, &mut count)?;
            }
            if record.len() > block_size {
                block_size = record.len() * 2;
            }
        }
        block.extend_from_slice(&record);
        count += 1;
    }
    if !block.is_empty() {
        flush(&mut out, &mut block, &mut count)?;
    }
    Ok(out)
}
