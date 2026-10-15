import asyncio
from dataclasses import dataclass
import json
import datetime
import uuid

import nats

import pytest

@pytest.mark.asyncio
async def test_set_tag():
    # Make sure that the tag manager has provisioned the tag bucket
    async with await nats.connect(servers="localhost:4222") as nc:
        js = nc.jetstream()

        indata = b"test"
        kv = await js.key_value("tag_bucket")
        await kv.put("core-integration-test.tags", indata)

        entry = await kv.get("core-integration-test.tags")

        assert entry.value == indata # TODO make sure python string comparison is correct
