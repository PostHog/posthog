use clickhouse_types::{Column, DataTypeNode};

use crate::codec::rowbinary::{RowBinaryRead, RowBinaryWrite};
use crate::codec::{CodecError, CodecResult};
use crate::io::column::{
    array_elem, read_bytes_col, read_float_col, read_int_array_i8, read_int_col, read_uuid_col,
    tuple_fields,
};
use crate::io::propval::{read_propval, read_propval_array, shape_output_type, write_propval};
use crate::trends::{Args, Event, ResultStruct};
use crate::types::BreakdownShape;

// Column layout per XML aggregate_funnel_trends{,_array_trends,_cohort_trends}:
//   0 UInt8    from_step
//   1 UInt8    to_step
//   2 UInt8    num_steps
//   3 UInt64   conversion_window_limit
//   4 String   breakdown_attribution_type
//   5 String   funnel_order_type
//   6 Array(<breakdown shape>)                                                     prop_vals
//   7 Array(Tuple(Nullable(Float64), UInt64, UUID, <breakdown shape>, Array(Int8))) value
const COLUMN_COUNT: usize = 8;

pub fn read_args<R: RowBinaryRead + ?Sized>(
    r: &mut R,
    shape: BreakdownShape,
    columns: &[Column],
) -> CodecResult<Args> {
    if columns.len() != COLUMN_COUNT {
        return Err(CodecError::SchemaLen {
            got: columns.len(),
            want: COLUMN_COUNT,
        });
    }

    let from_step = read_int_col(r, &columns[0].data_type)? as usize;
    let to_step = read_int_col(r, &columns[1].data_type)? as usize;
    let num_steps = read_int_col(r, &columns[2].data_type)? as usize;
    let conversion_window_limit = read_int_col(r, &columns[3].data_type)? as u64;
    let breakdown_attribution_type =
        String::from_utf8_lossy(&read_bytes_col(r, &columns[4].data_type)?).into_owned();
    let funnel_order_type =
        String::from_utf8_lossy(&read_bytes_col(r, &columns[5].data_type)?).into_owned();
    let prop_vals = read_propval_array(r, shape, &columns[6].data_type)?;

    let value_elem = array_elem(&columns[7].data_type, "value")?;
    let event_fields = tuple_fields(value_elem, 5, "value tuple")?;

    let value_len = r.read_varint()? as usize;
    let mut value = Vec::with_capacity(value_len);
    for _ in 0..value_len {
        value.push(read_event(r, shape, event_fields)?);
    }

    Ok(Args {
        from_step,
        to_step,
        num_steps,
        conversion_window_limit,
        breakdown_attribution_type,
        funnel_order_type,
        prop_vals,
        value,
    })
}

fn read_event<R: RowBinaryRead + ?Sized>(
    r: &mut R,
    shape: BreakdownShape,
    fields: &[DataTypeNode],
) -> CodecResult<Event> {
    let timestamp = read_float_col(r, &fields[0])?;
    let interval_start = read_int_col(r, &fields[1])? as u64;
    let uuid = read_uuid_col(r, &fields[2])?;
    let breakdown = read_propval(r, shape, &fields[3])?;
    let steps = read_int_array_i8(r, &fields[4])?;
    Ok(Event {
        timestamp,
        interval_start,
        uuid,
        breakdown,
        steps,
    })
}

pub fn output_columns(shape: BreakdownShape) -> Vec<Column> {
    let inner = DataTypeNode::Tuple(vec![
        DataTypeNode::UInt64,
        DataTypeNode::Int8,
        shape_output_type(shape),
        DataTypeNode::UUID,
    ]);
    vec![Column::new(
        "result".into(),
        DataTypeNode::Array(Box::new(inner)),
    )]
}

pub fn write_results<W: RowBinaryWrite + ?Sized>(
    w: &mut W,
    results: &[ResultStruct],
    shape: BreakdownShape,
) -> CodecResult<()> {
    w.write_varint(results.len() as u64)?;
    for r in results {
        w.write_u64_le(r.0)?;
        w.write_i8(r.1)?;
        write_propval(w, &r.2, shape)?;
        w.write_uuid(r.3)?;
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::types::{Bytes, PropVal};
    use uuid::Uuid;

    #[test]
    fn trends_args_roundtrip_strict_wire() {
        let uuid = Uuid::parse_str("550e8400-e29b-41d4-a716-446655440000").unwrap();
        let mut buf = Vec::new();
        buf.write_u8(0).unwrap();
        buf.write_u8(2).unwrap();
        buf.write_u8(3).unwrap();
        buf.write_u64_le(86_400).unwrap();
        buf.write_bytes(b"step_1").unwrap();
        buf.write_bytes(b"unordered").unwrap();
        buf.write_varint(1).unwrap();
        buf.write_varint(2).unwrap();
        buf.write_bytes(b"a").unwrap();
        buf.write_bytes(b"b").unwrap();
        buf.write_varint(1).unwrap();
        buf.write_u8(0).unwrap(); // timestamp not-null marker
        buf.write_f64_le(1.5).unwrap();
        buf.write_u64_le(1_700_000_000).unwrap();
        buf.write_uuid(uuid).unwrap();
        buf.write_varint(2).unwrap();
        buf.write_bytes(b"a").unwrap();
        buf.write_bytes(b"b").unwrap();
        buf.write_varint(3).unwrap();
        buf.write_i8(1).unwrap();
        buf.write_i8(2).unwrap();
        buf.write_i8(3).unwrap();

        let columns = vec![
            Column::new("from_step".into(), DataTypeNode::UInt8),
            Column::new("to_step".into(), DataTypeNode::UInt8),
            Column::new("num_steps".into(), DataTypeNode::UInt8),
            Column::new("conversion_window_limit".into(), DataTypeNode::UInt64),
            Column::new("breakdown_attribution_type".into(), DataTypeNode::String),
            Column::new("funnel_order_type".into(), DataTypeNode::String),
            Column::new(
                "prop_vals".into(),
                DataTypeNode::Array(Box::new(DataTypeNode::Array(Box::new(
                    DataTypeNode::String,
                )))),
            ),
            Column::new(
                "value".into(),
                DataTypeNode::Array(Box::new(DataTypeNode::Tuple(vec![
                    DataTypeNode::Nullable(Box::new(DataTypeNode::Float64)),
                    DataTypeNode::UInt64,
                    DataTypeNode::UUID,
                    DataTypeNode::Array(Box::new(DataTypeNode::String)),
                    DataTypeNode::Array(Box::new(DataTypeNode::Int8)),
                ]))),
            ),
        ];

        let mut slice = buf.as_slice();
        let args = read_args(&mut slice, BreakdownShape::ArrayString, &columns).unwrap();
        assert_eq!(args.from_step, 0);
        assert_eq!(args.to_step, 2);
        assert_eq!(args.num_steps, 3);
        assert_eq!(args.conversion_window_limit, 86_400);
        assert_eq!(args.prop_vals.len(), 1);
        assert_eq!(
            args.prop_vals[0],
            PropVal::Vec(vec![Bytes(b"a".to_vec()), Bytes(b"b".to_vec())])
        );
        assert_eq!(args.value.len(), 1);
        assert_eq!(args.value[0].timestamp, 1.5);
        assert_eq!(args.value[0].interval_start, 1_700_000_000);
        assert_eq!(args.value[0].uuid, uuid);
    }
}
