from prometheus_client import Counter, Histogram

# Declare prometheus metrics
prom_namespace_sophos = "symphony_module_sophos"

INCOMING_EVENTS = Counter(
    name="collected_events",
    documentation="Number of events collected from Sophos",
    namespace=prom_namespace_sophos,
    labelnames=["intake_key"],
)

# Declare prometheus metrics
prom_namespace = "symphony_module_common"

OUTCOMING_EVENTS = Counter(
    name="forwarded_events",
    documentation="Number of events forwarded to Sekoia.io",
    namespace=prom_namespace,
    labelnames=["intake_key"],
)

FORWARD_EVENTS_DURATION = Histogram(
    name="forward_events_duration",
    documentation="Duration to collect and forward events from Sophos",
    namespace=prom_namespace,
    labelnames=["intake_key"],
)
