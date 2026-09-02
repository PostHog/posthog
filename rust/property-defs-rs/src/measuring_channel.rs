use std::sync::{
    atomic::{AtomicUsize, Ordering},
    Arc,
};

use tokio::sync::mpsc::{
    channel,
    error::{SendError, TrySendError},
    Receiver, Sender,
};

#[derive(Clone, Debug)]
pub struct MeasuringSender<T> {
    sender: Sender<T>,
    in_flight: Arc<AtomicUsize>,
}

#[derive(Debug)]
pub struct MeasuringReceiver<T> {
    receiver: Receiver<T>,
    in_flight: Arc<AtomicUsize>,
}

pub fn measuring_channel<T>(capacity: usize) -> (MeasuringSender<T>, MeasuringReceiver<T>) {
    let (tx, rx) = channel(capacity);
    let counter = Arc::new(AtomicUsize::new(0));
    (
        MeasuringSender {
            sender: tx,
            in_flight: Arc::clone(&counter),
        },
        MeasuringReceiver {
            receiver: rx,
            in_flight: Arc::clone(&counter),
        },
    )
}

impl<T> MeasuringSender<T> {
    // Both senders count the message *before* handing it to the channel. Counting afterwards
    // leaves a window where the receiver has already dequeued the item and decremented, so the
    // subtraction runs first and wraps the unsigned counter to usize::MAX, where the gauge then
    // sits forever. On failure the item never entered the channel, so take the count back.
    pub fn try_send(&self, item: T) -> Result<(), TrySendError<T>> {
        self.in_flight.fetch_add(1, Ordering::Relaxed);
        let res = self.sender.try_send(item);
        if res.is_err() {
            self.in_flight.fetch_sub(1, Ordering::Relaxed);
        }
        res
    }

    pub async fn send(&self, item: T) -> Result<(), SendError<T>> {
        self.in_flight.fetch_add(1, Ordering::Relaxed);
        let res = self.sender.send(item).await;
        if res.is_err() {
            self.in_flight.fetch_sub(1, Ordering::Relaxed);
        }
        res
    }

    pub fn get_inflight_messages_count(&self) -> usize {
        self.in_flight.load(Ordering::Relaxed)
    }

    /// Slots still free. Note this is *remaining* capacity, not the channel's size; pair it with
    /// `max_capacity` to express occupancy.
    pub fn capacity(&self) -> usize {
        self.sender.capacity()
    }

    /// The channel's total size, which is fixed at construction.
    pub fn max_capacity(&self) -> usize {
        self.sender.max_capacity()
    }
}

impl<T> MeasuringReceiver<T> {
    pub async fn recv(&mut self) -> Option<T> {
        let res = self.receiver.recv().await;
        if res.is_some() {
            self.in_flight.fetch_sub(1, Ordering::Relaxed);
        }
        res
    }

    pub async fn recv_many(&mut self, buffer: &mut Vec<T>, limit: usize) -> usize {
        let res = self.receiver.recv_many(buffer, limit).await;
        if res > 0 {
            self.in_flight.fetch_sub(res, Ordering::Relaxed);
        }
        res
    }

    pub fn get_inflight_messages_count(&self) -> usize {
        self.in_flight.load(Ordering::Relaxed)
    }
}
