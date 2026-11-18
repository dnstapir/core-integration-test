import os
import uuid

import httpx
import nats
import pytest
import pytest_asyncio
from nats.js.errors import NoKeysError

API_URL = "http://127.0.0.1:8080"
API_KEY = "TEST_KEY"
NATS_URL = "localhost:4222"
BUCKET = "tag_bucket"


def flip(domain: str) -> str:
    """example.com -> com.example (lowercased, trailing dot removed)"""
    return ".".join(reversed(domain.lower().rstrip(".").split(".")))


def rand_domain(parent: str = "example.com") -> str:
    return f"{uuid.uuid4().hex[:8]}.{parent}"


def rand_tag() -> str:
    return f"pytest-{uuid.uuid4().hex[:8]}"


async def find_key(kv, tag, flipped, tag_class="custom"):
    """Find the bucket key for a tag on a domain, whatever the prefix is."""
    suffix = f"tags.{tag_class}.{tag}.{flipped}"
    try:
        keys = await kv.keys()
    except NoKeysError:
        return None
    return next((k for k in keys if k.endswith(suffix)), None)


@pytest_asyncio.fixture
async def post_tag(api, kv, auth):
    """POST a tag through the API and purge it from the bucket after the test."""
    created = []

    async def _post(domain, tag, value=None, tag_class="custom"):
        body = {"value": value} if value is not None else {}
        resp = await api.post(f"/domains/{domain}/tags/{tag}", json=body, headers=auth)
        assert resp.status_code == 201, resp.text
        created.append((domain, tag, tag_class))
        return resp

    yield _post

    for domain, tag, tag_class in created:
        key = await find_key(kv, tag, flip(domain), tag_class)
        if key:
            await kv.purge(key)

@pytest_asyncio.fixture
async def kv():
    nc = await nats.connect(servers=NATS_URL)
    try:
        js = nc.jetstream()
        yield await js.key_value(BUCKET)
    finally:
        await nc.close()


@pytest_asyncio.fixture
async def api():
    async with httpx.AsyncClient(base_url=API_URL, timeout=5) as client:
        yield client


@pytest.fixture
def auth():
    return {"X-API-Key": API_KEY}


@pytest.fixture
def unique():
    """A unique custom tag and domain per test, so runs never collide."""
    suffix = uuid.uuid4().hex[:8]
    tag = f"pytest-{suffix}"                   # matches ^[a-z0-9_-]+$, <= 60 chars
    domain = f"{suffix}.example.com"
    flipped = ".".join(reversed(domain.split(".")))   # com.example.<suffix>
    return tag, domain, flipped


@pytest.mark.asyncio
async def test_post_tag_is_stored_in_bucket(api, kv, auth, unique):
    tag, domain, flipped = unique
    value = "pytest was here"

    resp = await api.post(
        f"/domains/{domain}/tags/{tag}", json={"value": value}, headers=auth
    )
    assert resp.status_code == 201, resp.text

    key = await find_key(kv, tag, flipped)
    assert key is not None, f"no key ending in tags.custom.{tag}.{flipped}"

    entry = await kv.get(key)
    # The stored encoding may differ from the raw value, so check containment.
    assert value in entry.value.decode()

    await kv.purge(key)  # clean up, tags have no TTL


@pytest.mark.asyncio
async def test_post_normalizes_domain(api, kv, auth, unique):
    tag, domain, flipped = unique

    # Uppercase plus trailing dot should end up as the lowercase flipped domain
    resp = await api.post(
        f"/domains/{domain.upper()}./tags/{tag}", json={"value": "x"}, headers=auth
    )
    assert resp.status_code == 201, resp.text

    key = await find_key(kv, tag, flipped)
    assert key is not None

    await kv.purge(key)


@pytest.mark.asyncio
async def test_post_then_read_back_through_api(api, kv, auth, unique):
    tag, domain, flipped = unique

    r = await api.post(
        f"/domains/{domain}/tags/{tag}", json={"value": "hello"}, headers=auth
    )
    assert r.status_code == 201, r.text

    r = await api.get(f"/domains/{domain}/tags/{tag}", headers=auth)
    assert r.status_code == 200
    assert r.json()["value"] == "hello"

    r = await api.get(f"/domains/{domain}/tags", headers=auth)
    assert tag in r.json()["tags"]

    r = await api.get(f"/tags/{tag}/domains", headers=auth)
    assert domain in r.json()["domains"]

    r = await api.get("/custom/tags", headers=auth)
    assert tag in r.json()["custom"]

    key = await find_key(kv, tag, flipped)
    if key:
        await kv.purge(key)

@pytest.mark.skip(reason="api_auth_disabled")
@pytest.mark.asyncio
async def test_post_without_key_is_rejected(api, kv, unique):
    tag, domain, flipped = unique

    resp = await api.post(f"/domains/{domain}/tags/{tag}", json={"value": "nope"})
    assert resp.status_code == 401

    resp = await api.post(
        f"/domains/{domain}/tags/{tag}",
        json={"value": "nope"},
        headers={"X-API-Key": "definitely-wrong"},
    )
    assert resp.status_code == 401

    # And nothing must have been written
    assert await find_key(kv, tag, flipped) is None


@pytest.mark.asyncio
@pytest.mark.parametrize("tag", ["custom", "well-defined"])
async def test_reserved_tag_names_are_rejected(api, auth, tag):
    resp = await api.post(
        "/domains/example.com/tags/" + tag, json={"value": "x"}, headers=auth
    )
    assert resp.status_code == 422

# ---------- auth on every endpoint ----------

@pytest.mark.skip(reason="api_auth_disabled")
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "path",
    [
        "/well-defined/tags",
        "/custom/tags",
        "/tags/some-tag/domains",
        "/domains/example.com/tags",
        "/domains/example.com/tags/some-tag",
    ],
)
async def test_get_endpoints_require_api_key(api, path):
    assert (await api.get(path)).status_code == 401
    bad = await api.get(path, headers={"X-API-Key": "definitely-wrong"})
    assert bad.status_code == 401


# ---------- GET /well-defined/tags ----------

@pytest.mark.asyncio
async def test_get_well_defined(api, auth):
    resp = await api.get("/well-defined/tags", headers=auth)
    assert resp.status_code == 200
    tags = resp.json()["well-defined"]
    assert isinstance(tags, list) and tags
    assert all(isinstance(t, str) and t for t in tags)


# ---------- GET /custom/tags ----------

@pytest.mark.asyncio
async def test_get_custom_lists_new_tag_sorted(api, auth, post_tag):
    tag = rand_tag()
    await post_tag(rand_domain(), tag, "x")

    resp = await api.get("/custom/tags", headers=auth)
    assert resp.status_code == 200
    custom = resp.json()["custom"]
    assert tag in custom
    assert custom == sorted(custom)


@pytest.mark.asyncio
async def test_well_defined_tag_is_not_listed_as_custom(api, auth, post_tag):
    wd = (await api.get("/well-defined/tags", headers=auth)).json()["well-defined"][0]
    await post_tag(rand_domain(), wd, "x", tag_class="well-defined")

    custom = (await api.get("/custom/tags", headers=auth)).json()["custom"]
    assert wd not in custom


# ---------- GET /tags/{tag}/domains ----------

@pytest.mark.asyncio
async def test_get_tagged_domains_custom_tag(api, auth, post_tag):
    tag = rand_tag()
    d1, d2 = rand_domain(), rand_domain()
    await post_tag(d1, tag, "a")
    await post_tag(d2, tag, "b")

    resp = await api.get(f"/tags/{tag}/domains", headers=auth)
    assert resp.status_code == 200
    domains = resp.json()["domains"]
    assert sorted(domains) == sorted([d1, d2])
    assert domains == sorted(domains)


@pytest.mark.asyncio
async def test_get_tagged_domains_well_defined_tag(api, auth, post_tag):
    wd = (await api.get("/well-defined/tags", headers=auth)).json()["well-defined"][0]
    domain = rand_domain()
    await post_tag(domain, wd, "x", tag_class="well-defined")

    resp = await api.get(f"/tags/{wd}/domains", headers=auth)
    assert resp.status_code == 200
    assert domain in resp.json()["domains"]


@pytest.mark.asyncio
async def test_get_tagged_domains_unknown_tag_is_empty(api, auth):
    resp = await api.get(f"/tags/{rand_tag()}/domains", headers=auth)
    assert resp.status_code == 200
    assert resp.json()["domains"] == []


# ---------- GET /domains/{domain}/tags ----------

@pytest.mark.asyncio
async def test_get_domain_tags(api, auth, post_tag):
    domain = rand_domain()
    t1, t2 = rand_tag(), rand_tag()
    await post_tag(domain, t1, "a")
    await post_tag(domain, t2, "b")

    resp = await api.get(f"/domains/{domain}/tags", headers=auth)
    assert resp.status_code == 200
    tags = resp.json()["tags"]
    assert {t1, t2} <= set(tags)
    assert tags == sorted(tags)


@pytest.mark.asyncio
async def test_get_domain_tags_normalizes_domain(api, auth, post_tag):
    domain = rand_domain()
    tag = rand_tag()
    await post_tag(domain, tag, "a")

    resp = await api.get(f"/domains/{domain.upper()}./tags", headers=auth)
    assert resp.status_code == 200
    assert tag in resp.json()["tags"]


@pytest.mark.asyncio
async def test_get_domain_tags_does_not_include_subdomains(api, auth, post_tag):
    parent = rand_domain()
    child_tag = rand_tag()
    await post_tag(f"sub.{parent}", child_tag, "a")

    resp = await api.get(f"/domains/{parent}/tags", headers=auth)
    assert resp.status_code == 200
    assert child_tag not in resp.json()["tags"]


@pytest.mark.asyncio
async def test_get_domain_tags_untagged_domain_is_empty(api, auth):
    resp = await api.get(f"/domains/{rand_domain()}/tags", headers=auth)
    assert resp.status_code == 200
    assert resp.json()["tags"] == []


# ---------- GET /domains/{domain}/tags/{tag} ----------

@pytest.mark.asyncio
async def test_get_domain_tag_value(api, auth, post_tag):
    domain, tag = rand_domain(), rand_tag()
    await post_tag(domain, tag, "unusual behavior")

    resp = await api.get(f"/domains/{domain}/tags/{tag}", headers=auth)
    assert resp.status_code == 200
    body = resp.json()
    assert body["domain"] == domain
    assert body["tag"] == tag
    assert body["value"] == "unusual behavior"


@pytest.mark.asyncio
async def test_get_domain_tag_value_normalizes_domain(api, auth, post_tag):
    domain, tag = rand_domain(), rand_tag()
    await post_tag(domain, tag, "hi")

    resp = await api.get(f"/domains/{domain.upper()}./tags/{tag}", headers=auth)
    assert resp.status_code == 200
    assert resp.json()["domain"] == domain  # lowercased, no trailing dot


@pytest.mark.asyncio
async def test_post_with_empty_body_stores_empty_value(api, auth, post_tag):
    domain, tag = rand_domain(), rand_tag()
    await post_tag(domain, tag)  # sends {}

    resp = await api.get(f"/domains/{domain}/tags/{tag}", headers=auth)
    assert resp.status_code == 200
    assert resp.json()["value"] == ""


@pytest.mark.asyncio
async def test_post_without_body_stores_empty_value(api, kv, auth):
    domain, tag = rand_domain(), rand_tag()

    # No json= / content= at all: no body and no Content-Type header
    resp = await api.post(f"/domains/{domain}/tags/{tag}", headers=auth)

    try:
        assert resp.status_code == 201, resp.text

        resp = await api.get(f"/domains/{domain}/tags/{tag}", headers=auth)
        assert resp.status_code == 200
        assert resp.json()["value"] == ""
    finally:
        key = await find_key(kv, tag, flip(domain))
        if key:
            await kv.purge(key)


# ---------- input validation (rejected before touching NATS) ----------

@pytest.mark.asyncio
@pytest.mark.parametrize(
    "path",
    [
        "/tags/UPPERCASE/domains",              # tag pattern
        f"/tags/{'a' * 61}/domains",            # tag maxLength 60
        "/domains/exa mple.com/tags",           # domain pattern
        "/domains/example.com/tags/UPPER",      # tag pattern
        f"/domains/example.com/tags/{'a' * 61}",
    ],
)
async def test_get_validation_errors(api, auth, path):
    resp = await api.get(path, headers=auth)
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_post_value_too_long_is_rejected(api, auth):
    resp = await api.post(
        f"/domains/{rand_domain()}/tags/{rand_tag()}",
        json={"value": "x" * 101},
        headers=auth,
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_post_invalid_tag_is_rejected(api, auth):
    resp = await api.post(
        f"/domains/{rand_domain()}/tags/Bad_Tag", json={"value": "x"}, headers=auth
    )
    assert resp.status_code == 422
