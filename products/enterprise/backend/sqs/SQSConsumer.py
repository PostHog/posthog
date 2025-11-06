import time
import logging
from abc import ABC, abstractmethod
from typing import Any, cast

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)


# This is a base class for consuming messages from an AWS SQS queue.
class SQSConsumer(ABC):
    """
    Abstract base class for consuming messages from an AWS SQS queue.
    Subclasses must implement the process_message method.
    """

    def __init__(self, queue_url: str, region_name: str = "us-east-1", wait_time_seconds: int = 20):
        """
        Initialize the SQS consumer.

        Args:
            queue_url: The URL of the SQS queue to consume from
            region_name: AWS region name
            wait_time_seconds: Long polling wait time in seconds (0-20)
        """
        self.queue_url = queue_url
        self.region_name = region_name
        self.wait_time_seconds = wait_time_seconds

        # Initialize SQS client
        self.sqs = boto3.client(
            "sqs",
            region_name=region_name,
        )

    @abstractmethod
    def process_message(self, message: dict[str, Any]) -> None:
        """
        Process a single SQS message. Must be implemented by subclasses.

        Args:
            message: The SQS message to process
        """
        pass

    def receive_messages(self, max_messages: int = 10) -> list[dict[str, Any]]:
        """
        Receive messages from the SQS queue.

        Args:
            max_messages: Maximum number of messages to receive (1-10)

        Returns:
            List of SQS messages
        """
        try:
            response = self.sqs.receive_message(
                QueueUrl=self.queue_url,
                MaxNumberOfMessages=max(1, min(max_messages, 10)),  # Ensure between 1-10
                WaitTimeSeconds=self.wait_time_seconds,
                AttributeNames=["All"],
                MessageAttributeNames=["All"],
            )

            messages = response.get("Messages", [])
            if messages:
                logger.info(f"Received {len(messages)} messages from queue")
            return cast(list[dict[str, Any]], messages)

        except ClientError as e:
            logger.exception(f"Error receiving messages: {e}")
            return []

    def delete_message(self, receipt_handle: str) -> bool:
        """
        Delete a message from the queue after processing.

        Args:
            receipt_handle: The receipt handle of the message to delete

        Returns:
            bool: True if successful, False otherwise
        """
        try:
            self.sqs.delete_message(
                QueueUrl=self.queue_url,
                ReceiptHandle=receipt_handle,
            )
            return True
        except ClientError as e:
            logger.exception(f"Error deleting message: {e}")
            return False

    def run(self, max_messages: int = 10, continuous: bool = True) -> None:
        """
        Run the consumer to process messages.

        Args:
            max_messages: Maximum number of messages to receive in each batch
            continuous: Whether to continuously poll for messages
        """
        try:
            while True:
                messages = self.receive_messages(max_messages=max_messages)

                for message in messages:
                    try:
                        self.process_message(message)
                    except Exception as e:
                        logger.exception(f"Error processing message {message.get('MessageId')}: {e}")

                if not continuous:
                    break

                # If no messages were received, add a small delay to prevent tight polling
                if not messages:
                    time.sleep(1)

        except KeyboardInterrupt:
            logger.info("Consumer stopped by user")
        except Exception as e:
            logger.exception(f"Unexpected error in consumer: {e}")
