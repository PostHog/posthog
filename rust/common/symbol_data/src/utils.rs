use crate::error::Error;

pub fn assert_at_least_as_long_as(expected: usize, actual: usize) -> Result<(), Error> {
    if expected <= actual {
        Ok(())
    } else {
        Err(Error::DataTooShort(expected as u64, actual as u64))
    }
}
