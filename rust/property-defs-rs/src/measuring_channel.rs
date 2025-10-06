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
    pub fn try_send(&self, item: T) -> Result<(), TrySendError<T>> {
        let res = self.sender.try_send(item);
        if res.is_ok() {
            self.in_flight.fetch_add(1, Ordering::Relaxed);
        }
        res
    }

    pub async fn send(&self, item: T) -> Result<(), SendError<T>> {
        let res = self.sender.send(item).await;
        if res.is_ok() {
            self.in_flight.fetch_add(1, Ordering::Relaxed);
        }
        res
    }

    pub fn get_inflight_messages_count(&self) -> usize {
        self.in_flight.load(Ordering::Relaxed)
    }

    pub fn capacity(&self) -> usize {
        self.sender.capacity()
    }

    pub fn inner(&self) -> &Sender<T> {
        &self.sender
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

    pub fn inner(&self) -> &Receiver<T> {
        &self.receiver
    }

    pub fn get_inflight_messages_count(&self) -> usize {
        self.in_flight.load(Ordering::Relaxed)
    }
}
