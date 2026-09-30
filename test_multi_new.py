import asyncio
import json
import time
import uuid

import nats
import pytest

from test_basic import gen_event

EVENT_SUBJECT = "core-integration-test.events.new_qname"
OBSERVATION_SUBJECT = "core-integration-test.out"
SLD = "multi-new.xa"
THRESHOLD = 4
WINDOW = 10

# tag_mask the analyst emits when the threshold is crossed.
EXPECTED_BELOW_THRESHOLD_TAG_MASK = 1 # globally_new (1)
EXPECTED_ABOVE_THRESHOLD_TAG_MASK = 3 # globally_new (1) plus multi_new (2)


async def publish_from_edges(nc, domain, edges, delay=0, dupes=False):
    """Publish the same new_qname event once per edge, each with its own thumbprint."""
    event = gen_event(domain)
    for i in range(1, edges + 1):
        if i == 2: # sleep before sending from 2nd edge
            time.sleep(delay)
        
        edgeID = 1 if dupes else i

        await nc.publish(
            EVENT_SUBJECT,
            event.to_json().encode("UTF-8"),
            headers={"DNSTAPIR-Key-Thumbprint": f"edge-{edgeID}"},
        )
        await nc.flush()
        time.sleep(0.2)


async def observations_for(sub, domain, window):
    """Collect observations naming `domain` until `window` seconds have passed.

    Observations for other domains (e.g. from other tests) are ignored.
    """
    found = []
    deadline = time.monotonic() + window
    while (remaining := deadline - time.monotonic()) > 0:
        try:
            msg = await sub.next_msg(timeout=remaining)
        except nats.errors.TimeoutError:
            break
        obs = json.loads(msg.data.decode())
        found.extend(a for a in obs.get("added", []) if a["name"] == domain)
    return found


@pytest.mark.asyncio
async def test_below_threshold_no_observation():
    # Fresh name per run: the analyst state lives in a bucket without TTL.
    domain = f"no-{uuid.uuid4().hex}-{SLD}"

    async with await nats.connect(servers="localhost:4222") as nc:
        sub = await nc.subscribe(OBSERVATION_SUBJECT)
        await nc.flush()

        await publish_from_edges(nc, domain, edges=THRESHOLD-1)

        added = await observations_for(sub, domain, window=2)

    masks = [a["tag_mask"] for a in added]
    assert len(added) == 1, f"unexpected number of observations for below-threshold: {len(added)}"
    assert all(m == EXPECTED_BELOW_THRESHOLD_TAG_MASK for m in masks), f"unexpected tag masks: {masks}"


@pytest.mark.asyncio
async def test_above_threshold_observation():
    domain = f"yes-{uuid.uuid4().hex}-{SLD}"

    async with await nats.connect(servers="localhost:4222") as nc:
        sub = await nc.subscribe(OBSERVATION_SUBJECT)
        await nc.flush()

        await publish_from_edges(nc, domain, edges=THRESHOLD)

        added = await observations_for(sub, domain, window=2)
        assert len(added) == 2, f"unexpected number of observations for above threshold: {len(added)}"
        assert added[-1]["tag_mask"] == EXPECTED_ABOVE_THRESHOLD_TAG_MASK


@pytest.mark.asyncio
async def test_outside_window_no_observation():
    domain = f"delay-{uuid.uuid4().hex}-{SLD}"

    async with await nats.connect(servers="localhost:4222") as nc:
        sub = await nc.subscribe(OBSERVATION_SUBJECT)
        await nc.flush()

        await publish_from_edges(nc, domain, edges=THRESHOLD, delay=WINDOW+2) # sleep between 1st and 2nd edge

        added = await observations_for(sub, domain, window=2)

    assert len(added) == 1, f"unexpected number of observations for outside-window: {len(added)}"
    masks = [a["tag_mask"] for a in added]
    assert all(m == EXPECTED_BELOW_THRESHOLD_TAG_MASK for m in masks), f"unexpected tag masks: {masks}"


@pytest.mark.asyncio
async def test_duplicates_no_observation():
    domain = f"dupes-{uuid.uuid4().hex}-{SLD}"

    async with await nats.connect(servers="localhost:4222") as nc:
        sub = await nc.subscribe(OBSERVATION_SUBJECT)
        await nc.flush()

        await publish_from_edges(nc, domain, edges=THRESHOLD, dupes=True)

        added = await observations_for(sub, domain, window=2)

    assert len(added) == 1, f"unexpected number of observations for duplicates: {len(added)}"
    masks = [a["tag_mask"] for a in added]
    assert all(m == EXPECTED_BELOW_THRESHOLD_TAG_MASK for m in masks), f"unexpected tag masks: {masks}"
