use std::sync::atomic::{AtomicUsize, Ordering};

use tokio::sync::mpsc::{channel, error::{RecvError, SendError}, Receiver, Sender};

pub struct MeasuringChannel<T> {
    sender: Sender<T>,
    receiver: Receiver<T>,
    in_flight_message: AtomicUsize,
}

impl<T> MeasuringChannel<T> {
    pub fn new(capacity: usize) -> Self {
        let (tx, rx) = channel(capacity);
        Self {
            sender: tx,
            receiver: rx,
            in_flight_message: AtomicUsize::new(0),
        }
    }

    pub async fn send(&self, item: T) -> Result<(), SendError<T>> {
        let result = self.sender.send(item).await;
        if result.is_ok() {
            self.in_flight_message.fetch_add(1, Ordering::Relaxed);
        }
        result

    pub async fn recv(&mut self) -> Option<T> {
        let result = self.receiver.recv().await;
        if result.is_some() {
            self.in_flight_message.fetch_sub(1, Ordering::Relaxed);
        }
        result
    }

    pub async fn recv_many(&mut self, buffer: &mut Vec<T>, limit: usize) -> usize {
        let received_count = self.receiver.recv_many(buffer, limit).await;
        self.in_flight_message.fetch_sub(received_count, Ordering::Relaxed);
        received_count
    }

    pub fn len(&self) -> usize {
        self.in_flight_message.load(Ordering::Relaxed)
    }

    pub fn tx(&self) -> &Sender<T> {
        &self.sender
    }

    pub fn rx(&self) -> &Receiver<T> {
        &self.receiver
    }

    pub fn capacity(&self) -> usize {
        self.sender.capacity()
    }
}