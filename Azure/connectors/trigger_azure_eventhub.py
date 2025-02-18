import os
import signal
import time
from functools import cached_property
from threading import Event
from typing import Any, Optional

import orjson
from azure.eventhub import EventData, EventHubConsumerClient, PartitionContext
from azure.eventhub.extensions.checkpointstoreblob import BlobCheckpointStore
from sekoia_automation.connector import Connector, DefaultConnectorConfiguration

from helpers.kafka_forwarder import KafkaForwarder
from helpers.prometheus_exporter import make_prometheus_exporter

from .metrics import FORWARD_EVENTS_DURATION, INCOMING_MESSAGES, OUTCOMING_EVENTS


class AzureEventsHubConfiguration(DefaultConnectorConfiguration):
    hub_connection_string: str
    hub_name: str
    hub_consumer_group: str
    storage_connection_string: str
    storage_container_name: str


class Client(object):
    _client: EventHubConsumerClient | None = None

    def __init__(self, configuration: AzureEventsHubConfiguration) -> None:
        self.configuration = configuration
        self._client = None

    @cached_property
    def checkpoint_store(self) -> BlobCheckpointStore:
        return BlobCheckpointStore.from_connection_string(
            self.configuration.storage_connection_string,
            container_name=self.configuration.storage_container_name,
        )

    def _new_client(self) -> EventHubConsumerClient:
        return EventHubConsumerClient.from_connection_string(
            self.configuration.hub_connection_string,
            self.configuration.hub_consumer_group,
            eventhub_name=self.configuration.hub_name,
            checkpoint_store=self.checkpoint_store,
        )

    def receive_batch(self, *args: Any, **kwargs: Optional[Any]) -> None:
        self._client = self._new_client()
        try:
            self._client.receive_batch(*args, **kwargs)  # type: ignore
        finally:
            self.close()

    def close(self) -> None:
        if self._client:
            self._client.close()
            self._client = None


class AzureEventsHubTrigger(Connector):
    """
    This trigger consumes messages from Microsoft Azure EventHub
    """

    configuration: AzureEventsHubConfiguration

    def __init__(self, *args: Any, **kwargs: Optional[Any]) -> None:
        super().__init__(*args, **kwargs)
        self._stop_event = Event()
        self._consumption_max_wait_time = int(os.environ.get("CONSUMER_MAX_WAIT_TIME", "600"), 10)

        # Register signal to terminate thread
        signal.signal(signal.SIGINT, self.stop)
        signal.signal(signal.SIGTERM, self.stop)

    def stop(self, *args: Any, **kwargs: Optional[Any]) -> None:
        self.log(message="Stopping Azure EventHub connector", level="info")
        # Exit signal received, asking the processor to stop
        self._stop_event.set()

        # Close the azure EventHub client
        self.client.close()

    @cached_property
    def client(self) -> Client:
        return Client(self.configuration)

    @cached_property
    def kafka_producer(self) -> KafkaForwarder:
        return KafkaForwarder()

    def handle_messages(self, partition_context: PartitionContext, messages: list[EventData]) -> None:
        """
        Handle new messages
        """
        if len(messages) > 0:
            # got messages, we forward them
            self.forward_events(messages)
        else:
            # We reached the max_wait_time, close the current client
            self.log(
                message=(
                    f"No new messages received from the last {self._consumption_max_wait_time} seconds. "
                    "Close the current client"
                ),
                level="info",
            )
            self.client.close()

        # acknowledge the messages
        partition_context.update_checkpoint()

    def forward_events(self, messages: list[EventData]) -> None:
        INCOMING_MESSAGES.labels(intake_key=self.configuration.intake_key).inc(len(messages))
        start = time.time()
        records = [
            orjson.dumps(record).decode("utf-8")
            for message in messages
            for record in message.body_as_json().get("records", [])
            if record is not None
        ]

        if len(records) > 0:
            self.log(
                message=f"Forward {len(records)} events",
                level="info",
            )
            OUTCOMING_EVENTS.labels(intake_key=self.configuration.intake_key).inc(len(records))
            self.kafka_producer.produce(records)
            self.push_events_to_intakes(events=records)
        else:
            self.log(
                message="No events to forward",
                level="info",
            )

        FORWARD_EVENTS_DURATION.labels(intake_key=self.configuration.intake_key).observe(time.time() - start)

    def handle_exception(self, partition_context: PartitionContext, exception: Exception) -> None:
        self.log_exception(
            exception,
            message="Error raised when consuming messages",
        )

    def run(self) -> None:  # pragma: no cover
        # start the prometheus exporter
        exporter = make_prometheus_exporter(int(os.environ.get("WORKER_PROM_LISTEN_PORT", "8010"), 10))
        exporter.start()

        self.log(message="Azure EventHub Trigger has started", level="info")

        try:
            while not self._stop_event.is_set():
                try:
                    self.client.receive_batch(
                        self.handle_messages,
                        on_error=self.handle_exception,
                        max_wait_time=self._consumption_max_wait_time,
                    )
                except Exception as ex:
                    self.log_exception(ex, message="Failed to consume messages")
                    raise ex
        finally:
            exporter.stop()
