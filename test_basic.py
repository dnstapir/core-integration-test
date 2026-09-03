import asyncio
from dataclasses import dataclass
import json
import datetime

import nats

import pytest

@dataclass
class NewQnameEvent:
    qname:     str
    timestamp: str
    flags:     int = 33155
    qclass:    int = 1
    qtype:     int = 28
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

def gen_event(domain):
    timestamp = datetime.datetime.now(datetime.UTC).isoformat()
    return NewQnameEvent(qname=domain, timestamp=timestamp)


async def send_event_and_check(
    event, event_subject, thumbprint, observation_subject, domain, expected
):
    # The observation subject is a plain NATS subject, so the server drops
    # messages published to it while nobody is subscribed. Subscribe and flush
    # before publishing the input event, otherwise a fast analyst can emit the
    # observation before the subscription reaches the server and next_msg()
    # times out on a system that is working correctly.
    #
    # Using the client as a context manager closes the connection on every exit
    # path, including a failure in subscribe() or flush() before the publish.
    async with await nats.connect(servers="localhost:4222") as nc:
        sub = await nc.subscribe(observation_subject)
        await nc.flush()

        headers = {
                "DNSTAPIR-Key-Thumbprint": thumbprint
        }

        await nc.publish(event_subject, event.to_json().encode('UTF-8'), headers = headers)
        await nc.flush()

        msg = await sub.next_msg(timeout=10)
        await handle_observation(msg.data.decode(), domain, expected)

async def handle_observation(obsJSON, domain, expected):
    obs = json.loads(obsJSON)

    assert obs["added"][0]["name"] == domain
    assert obs["added"][0]["tag_mask"] == expected


#######################################################################
############# SOME SANITY TESTS #######################################
#######################################################################
def test_true():
    assert True

def test_to_json_and_back():
    event = gen_event("leon.xa.")
    eventJSON = event.to_json()
    eventCopy = NewQnameEvent.from_json(eventJSON)

    assert event == eventCopy

#######################################################################
############# SOME REAL TESTS #########################################
#######################################################################

@pytest.mark.asyncio
async def test_looptest():
    domain = "test.from-edge.looptest.dnstapir.se"
    expected_obs = 1024

    event = gen_event(domain)
    subject = "core-integration-test.events.new_qname"
    thumbprint = "thumbprint1"

    await send_event_and_check(
        event,
        subject,
        thumbprint,
        "core-integration-test.out",
        domain,
        expected_obs,
    )

@pytest.mark.asyncio
async def test_new_qname():
    domain = "example.xa"
    expected_obs = 1

    event = gen_event(domain)
    subject = "core-integration-test.events.new_qname"
    thumbprint = "thumbprint1"

    await send_event_and_check(
        event,
        subject,
        thumbprint,
        "core-integration-test.out",
        domain,
        expected_obs,
    )

@pytest.mark.skip
@pytest.mark.asyncio
async def test_registry_investigation():
    # Might be flaky since this new_qname event causes two analysts to
    # fire at once, thus triggering two observation messages to be sent
    # out by the observation encoder. Most of the time, the messages
    # seem to be identical, but this is not guaranteed.
    #
    # In the future, the observation encoder should buffer a number of
    # messages before sending them out in order to prevent multiple
    # outgoing messages with similar contents to be sent out in
    # scenarios where multiple analysts set observation flags
    # simultaneously.

    domain = "example.com"
    expected_obs = 9

    event = gen_event(domain)
    subject = "core-integration-test.events.new_qname"
    thumbprint = "thumbprint1"

    await send_event_and_check(
        event,
        subject,
        thumbprint,
        "core-integration-test.out",
        domain,
        expected_obs,
    )

@pytest.mark.asyncio
async def test_registry_investigation_single():
    # .org domains should be filtered in the new_qname analysts, thus
    # only the registry_investigation flag should be set during this
    # test.
    domain = "example.org"
    expected_obs = 8

    event = gen_event(domain)
    subject = "core-integration-test.events.new_qname"
    thumbprint = "thumbprint1"

    await send_event_and_check(
        event,
        subject,
        thumbprint,
        "core-integration-test.out",
        domain,
        expected_obs,
    )
