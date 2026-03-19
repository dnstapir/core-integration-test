import asyncio
from dataclasses import dataclass
import json
import datetime

import nats

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


async def send_event(event, subject, thumbprint):
    nc = await nats.connect(servers="localhost:4222")

    headers = {
            "DNSTAPIR-Key-Thumbprint": thumbprint
    }

    await nc.publish(subject, event.to_json().encode('UTF-8'), headers = headers)


#######################################################################
############# SOME SANITY TESTS #######################################
#######################################################################
def test_true():
    assert True

def test_to_json_and_back():
    event = gen_event("leon.xa.")
    eventJSON = event.to_json()
    print(eventJSON)
    eventCopy = NewQnameEvent.from_json(eventJSON)

    assert event == eventCopy

#######################################################################
############# SOME REAL TESTS #########################################
#######################################################################

def test_send():
    event = gen_event("leon.xa.")
    subject = "core-integration-test.events.new_qname"
    thumbprint = "thumbprint1"
    asyncio.run(send_event(event, subject, thumbprint))
