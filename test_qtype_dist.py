import asyncio
from dataclasses import dataclass
import json
import datetime
import uuid

import nats

import pytest

from nats.js.errors import KeyNotFoundError, KeyWrongLastSequenceError

# From the analyst's NATS config:
PRIVATE_BUCKET = "tapir-analyse-qtype-dist_bucket"  # private_bucket.name
PRIVATE_PREFIX = "core-integration-test.service.tapir-analyse-qtype-dist"  # private_subject_prefix
EVENT_SUBJECT = "core-integration-test.events.new_qname"
THUMBPRINT = "thumbprint1"

# Private-use qtypes (RFC 6895): real traffic never uses them, so the global
# counters for them are only touched by these tests and can be checked exactly.
TEST_QTYPE = 65281
CONTROL_QTYPE = 65282


@dataclass
class NewQnameEvent:
    qname:     str
    timestamp: str
    qtype:     int
    flags:     int = 33155
    qclass:    int = 1
    type:      str = "new_qname"
    version:   int = 0

    def to_json(self):
        j = "{"
        j += f"\"qname\": \"{self.qname}\","
        j += f"\"timestamp\": \"{self.timestamp}\","
        j += f"\"flags\": {self.flags},"
        j += f"\"qclass\": {self.qclass},"
        j += f"\"qtype\": {self.qtype},"
        j += f"\"type\": \"{self.type}\","
        j += f"\"version\": {self.version}"
        j += "}"
        return j

    @staticmethod
    def from_json(j):
        d = json.loads(j)
        nq = NewQnameEvent(
            qname     = d["qname"],
            timestamp = d["timestamp"],
            flags     = d["flags"],
            qclass    = d["qclass"],
            qtype     = d["qtype"],
            type      = d["type"],
            version   = d["version"]
        )

        return nq

def gen_event(domain, qtype):
    timestamp = datetime.datetime.now(datetime.UTC).isoformat()
    return NewQnameEvent(qname=domain, qtype=qtype, timestamp=timestamp)


def flip(domain: str) -> str:
    return ".".join(reversed(domain.strip(".").lower().split(".")))


async def cas_increment(kv, key: str):
    """Increment a counter with compare-and-swap, the same protocol as the analyst."""
    while True:
        try:
            entry = await kv.get(key)
            cur, rev = int(entry.value.decode()), entry.revision
        except KeyNotFoundError:
            cur, rev = 0, 0  # last=0 means "only if the key doesn't exist"
        try:
            await kv.update(key, str(cur + 1).encode(), last=rev)
            return
        except KeyWrongLastSequenceError:
            await asyncio.sleep(0)  # lost the race, re-read and retry


async def hammer(kv, keys, n: int):
    for _ in range(n):
        for k in keys:
            await cas_increment(kv, k)


async def read_counter(kv, key: str) -> int:
    try:
        entry = await kv.get(key)
    except KeyNotFoundError:
        return 0
    return int(entry.value.decode())


async def wait_for_counter(kv, key: str, at_least: int, timeout: float = 10.0) -> int:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    current = 0
    while loop.time() < deadline:
        current = await read_counter(kv, key)
        if current >= at_least:
            return current
        await asyncio.sleep(0.1)
    raise AssertionError(f"{key}: expected >= {at_least}, last saw {current}")


def counter_key(date: str, scope: str, counter) -> str:
    part = "global" if scope == "global" else flip(scope)
    return f"{PRIVATE_PREFIX}.{date}.{part}.{counter}"


async def publish_event(nc, domain: str, qtype: int):
    headers = {"DNSTAPIR-Key-Thumbprint": THUMBPRINT}
    await nc.publish(
        EVENT_SUBJECT,
        gen_event(domain, qtype).to_json().encode("utf-8"),
        headers=headers,
    )
    await nc.flush()

#######################################################################
############# TESTS ###################################################
#######################################################################

@pytest.mark.asyncio
async def test_qtype_dist_counter():
    # A fresh registrable domain each run, so its counters start at zero
    etld_plus_one = f"{uuid.uuid4().hex}.se"
    domain = f"{uuid.uuid4().hex}.{uuid.uuid4().hex}.{etld_plus_one}"
    date = datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%d")

    domain_keys = [
        counter_key(date, etld_plus_one, TEST_QTYPE),
        counter_key(date, etld_plus_one, "total"),
    ]
    global_qtype_key = counter_key(date, "global", TEST_QTYPE)
    global_total_key = counter_key(date, "global", "total")

    async with await nats.connect(servers="localhost:4222") as nc:
        kv = await nc.jetstream().key_value(PRIVATE_BUCKET)

        # Counters persist between runs, so compare against a baseline
        keys = domain_keys + [global_qtype_key, global_total_key]
        before = {k: await read_counter(kv, k) for k in keys}

        await publish_event(nc, domain, TEST_QTYPE)

        for k in keys:
            await wait_for_counter(kv, k, before[k] + 1)

        # The domain and the private-use qtype are only used by this test
        for k in domain_keys + [global_qtype_key]:
            assert await read_counter(kv, k) == before[k] + 1, f"{k}: wrong count"

        # global.total may also be hit by other traffic, so only >= is safe
        # (already waited for above)


@pytest.mark.asyncio
@pytest.mark.parametrize("tld", ["se", "global"])
async def test_qtype_dist_bare_tld(tld):
    # A bare TLD has no registrable domain, so it must not be counted at all,
    # neither under its own key nor in the global counters.
    date = datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%d")
    control_domain = f"{uuid.uuid4().hex}.se"
    control_key = counter_key(date, control_domain, CONTROL_QTYPE)

    # For tld="global" both keys are the same, which is exactly the collision
    watched = {
        counter_key(date, tld, TEST_QTYPE),
        counter_key(date, "global", TEST_QTYPE),
    }

    async with await nats.connect(servers="localhost:4222") as nc:
        kv = await nc.jetstream().key_value(PRIVATE_BUCKET)
        before = {k: await read_counter(kv, k) for k in watched}

        await publish_event(nc, tld, TEST_QTYPE)
        # Positive control: once this is counted, the analyst is alive and has
        # almost certainly handled the bare TLD event as well
        await publish_event(nc, control_domain, CONTROL_QTYPE)
        await wait_for_counter(kv, control_key, 1)
        await asyncio.sleep(0.5)  # the analyst has 3 workers, so ordering isn't guaranteed

        for k, v in before.items():
            assert await read_counter(kv, k) == v, f"bare TLD '{tld}' was counted at {k}"


@pytest.mark.asyncio
async def test_qtype_dist_counter_contention():
    # Analyst events and the test's own writes hit the same two keys concurrently.
    # With correct compare-and-swap no increment is lost, so the totals are exact.
    etld_plus_one = f"{uuid.uuid4().hex}.se"
    date = datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%d")

    n_events = 100
    n_hammers = 2
    n_each = 50  # increments per hammer, per key
    external = n_hammers * n_each

    shared_keys = [
        counter_key(date, etld_plus_one, TEST_QTYPE),
        counter_key(date, etld_plus_one, "total"),
    ]
    global_qtype_key = counter_key(date, "global", TEST_QTYPE)
    global_total_key = counter_key(date, "global", "total")

    async with await nats.connect(servers="localhost:4222") as nc:
        kv = await nc.jetstream().key_value(PRIVATE_BUCKET)

        keys = shared_keys + [global_qtype_key, global_total_key]
        before = {k: await read_counter(kv, k) for k in keys}

        async def publisher():
            for _ in range(n_events):
                await publish_event(nc, f"{uuid.uuid4().hex}.{etld_plus_one}", TEST_QTYPE)

        await asyncio.gather(
            publisher(),
            *[hammer(kv, shared_keys, n_each) for _ in range(n_hammers)],
        )

        # Wait until the analyst has caught up (everything it counts + our writes)
        expected = n_events + external
        for k in shared_keys:
            await wait_for_counter(kv, k, before[k] + expected, timeout=30)
        await wait_for_counter(kv, global_qtype_key, before[global_qtype_key] + n_events, timeout=30)
        await wait_for_counter(kv, global_total_key, before[global_total_key] + n_events, timeout=30)
        await asyncio.sleep(0.5)  # give any over-counting a chance to show up

        # Contended keys: exactly our increments plus the analyst's
        for k in shared_keys:
            assert await read_counter(kv, k) == before[k] + expected, f"{k}: lost or extra increments"

        # Only the analyst writes the global qtype counter
        assert await read_counter(kv, global_qtype_key) == before[global_qtype_key] + n_events
        # global.total may also be hit by other traffic, so only >= is safe (waited for above)
