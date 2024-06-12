use rand::RngCore;
use uuid::Uuid;

pub fn random_bytes<const N: usize>() -> [u8; N] {
    let mut ret = [0u8; N];
    rand::thread_rng().fill_bytes(&mut ret);
    ret
}

// basically just ripped from the uuid crate. they have it as unstable, but we can use it fine.
const fn encode_unix_timestamp_millis(millis: u64, random_bytes: &[u8; 10]) -> Uuid {
    let millis_high = ((millis >> 16) & 0xFFFF_FFFF) as u32;
    let millis_low = (millis & 0xFFFF) as u16;

    let random_and_version =
        (random_bytes[0] as u16 | ((random_bytes[1] as u16) << 8) & 0x0FFF) | (0x7 << 12);

    let mut d4 = [0; 8];

    d4[0] = (random_bytes[2] & 0x3F) | 0x80;
    d4[1] = random_bytes[3];
    d4[2] = random_bytes[4];
    d4[3] = random_bytes[5];
    d4[4] = random_bytes[6];
    d4[5] = random_bytes[7];
    d4[6] = random_bytes[8];
    d4[7] = random_bytes[9];

    Uuid::from_fields(millis_high, millis_low, random_and_version, &d4)
}

pub fn uuid_v7() -> Uuid {
    let bytes = random_bytes();
    let now = time::OffsetDateTime::now_utc();
    let now_millis: u64 = now.unix_timestamp() as u64 * 1_000 + now.millisecond() as u64;

    encode_unix_timestamp_millis(now_millis, &bytes)
}
