import asyncio
import time
import uuid

import nats
import pytest
from nats.js.errors import KeyNotFoundError, NoKeysError


NATS_SERVER = "localhost:4222"

# Must match the analyst's config (tags, allow_custom = true, observation)
TAG_BUCKET = "tag_bucket"
TAG_PREFIX = "core-integration-test.tags"
TAGS = ["tag1", "tag2"]

# Adjust to your observation bucket config
OBS_BUCKET = "dns_tunnel_bucket"
OBS_PREFIX = "core-integration-test.observations"
OBS_NAME = "dns_tunnel"
ANALYST_ID = "tapir-analyse-tag-aggregator"  

WINDOW = 3  # seconds to wait for an observation; must exceed the 2s ListTagKeys timeout


def flip(domain):
    return ".".join(reversed(domain.split(".")))


def tag_key(tag, domain):
    # Custom tags only. A tag that common.StringToTag recognizes would use "well-defined"
    return f"{TAG_PREFIX}.custom.{tag}.{flip(domain)}"


def obs_key(domain):
    return f"{OBS_PREFIX}.{OBS_NAME}.{flip(domain)}"


async def put_tags(tags_kv, domain, tags, delay=0.2):
    """Put each tag for `domain`, one at a time."""
    for t in tags:
        await tags_kv.put(tag_key(t, domain), b"1")
        await asyncio.sleep(delay)


async def observation_for(obs_kv, domain, window):
    """Poll for an observation on `domain` until `window` seconds have passed.

    Returns the entry, or None if nothing appeared. Observations for other
    domains (e.g. from other tests) are never looked at.
    """
    key = obs_key(domain)
    deadline = time.monotonic() + window
    while time.monotonic() < deadline:
        try:
            return await obs_kv.get(key)
        except KeyNotFoundError:
            await asyncio.sleep(0.1)
    return None


async def clear_domain(tags_kv, obs_kv, domain):
    """Remove every tag and the observation stored for `domain`."""
    suffix = f".{flip(domain)}"

    # Tags: find every key under our prefix that belongs to this domain,
    # so it also catches tags not listed in TAGS (e.g. "some_other_tag").
    try:
        keys = await tags_kv.keys()
    except NoKeysError:
        keys = []

    for key in keys:
        if key.startswith(TAG_PREFIX) and key.endswith(suffix):
            await tags_kv.purge(key)

    # Observation (purge is harmless if the key doesn't exist)
    try:
        await obs_kv.purge(obs_key(domain))
    except KeyNotFoundError:
        pass


@pytest.mark.asyncio
async def test_all_tags_present_sets_observation():
    # Fresh name per run: the buckets are not cleaned between runs
    domain = f"yes.xa"

    async with await nats.connect(servers=NATS_SERVER) as nc:
        js = nc.jetstream()
        tags_kv = await js.key_value(TAG_BUCKET)
        obs_kv = await js.key_value(OBS_BUCKET)

        try:
            await put_tags(tags_kv, domain, TAGS)
            entry = await observation_for(obs_kv, domain, window=WINDOW)

            assert entry is not None, "observation was never set"
            assert entry.value.decode() == ANALYST_ID
        finally:
            await clear_domain(tags_kv, obs_kv, domain)


@pytest.mark.asyncio
async def test_missing_tag_no_observation():
    domain = f"no.xa"

    async with await nats.connect(servers=NATS_SERVER) as nc:
        js = nc.jetstream()
        tags_kv = await js.key_value(TAG_BUCKET)
        obs_kv = await js.key_value(OBS_BUCKET)

        try:
            await put_tags(tags_kv, domain, TAGS[:-1])  # all but the last tag
            entry = await observation_for(obs_kv, domain, window=WINDOW)

            assert entry is None, "observation set although a tag is missing"
        finally:
            await clear_domain(tags_kv, obs_kv, domain)


@pytest.mark.asyncio
async def test_late_tag_completes_set():
    domain = f"late.xa"

    async with await nats.connect(servers=NATS_SERVER) as nc:
        js = nc.jetstream()
        tags_kv = await js.key_value(TAG_BUCKET)
        obs_kv = await js.key_value(OBS_BUCKET)

        try:
            await put_tags(tags_kv, domain, TAGS[:-1])
            early = await observation_for(obs_kv, domain, window=WINDOW)

            await put_tags(tags_kv, domain, TAGS[-1:])
            late = await observation_for(obs_kv, domain, window=WINDOW)

            assert early is None, "observation set before the last tag arrived"
            assert late is not None, "observation not set after the last tag arrived"
        finally:
            await clear_domain(tags_kv, obs_kv, domain)


@pytest.mark.asyncio
async def test_unrelated_tag_no_observation():
    domain = f"other.xa"

    async with await nats.connect(servers=NATS_SERVER) as nc:
        js = nc.jetstream()
        tags_kv = await js.key_value(TAG_BUCKET)
        obs_kv = await js.key_value(OBS_BUCKET)

        try:
            await put_tags(tags_kv, domain, TAGS[:-1])

            # Not in the analyst's tags list, so it is filtered out by the watcher
            await put_tags(tags_kv, domain, ["some_other_tag"])
            entry = await observation_for(obs_kv, domain, window=WINDOW)

            assert entry is None, "observation set for a tag the analyst is not configured for"
        finally:
            await clear_domain(tags_kv, obs_kv, domain)
