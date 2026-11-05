use std::collections::HashSet;

use super::in_flight::RequestId;
use super::RevokeId;

#[derive(Default)]
pub struct PartitionDrains {
    pending: Vec<PartitionDrain>,
}

struct PartitionDrain {
    revoke: RevokeId,
    carrying: HashSet<RequestId>,
}

impl PartitionDrains {
    pub fn on_revoked(&mut self, revoke: RevokeId, carrying: impl IntoIterator<Item = RequestId>) {
        self.pending.push(PartitionDrain {
            revoke,
            carrying: carrying.into_iter().collect(),
        });
    }

    pub fn on_request_settled(&mut self, request: RequestId) {
        for drain in &mut self.pending {
            drain.carrying.remove(&request);
        }
    }

    pub fn take_drained(&mut self) -> Vec<RevokeId> {
        let (drained, pending): (Vec<_>, Vec<_>) = std::mem::take(&mut self.pending)
            .into_iter()
            .partition(|drain| drain.carrying.is_empty());
        self.pending = pending;
        drained.into_iter().map(|drain| drain.revoke).collect()
    }
}
