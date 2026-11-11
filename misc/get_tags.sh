#!/bin/bash

tags=(
    "internal_testing"
    "anomalous_qtype_distribution"
    "my_custom_tag"
)

domain="foo.bar"
value="foobookee"

# Get a list of well-defined tags
curl localhost:8080/well-defined/tags

# Get a list of in-use custom tags
curl localhost:8080/custom/tags

# Get a list of domains with tag
curl localhost:8080/tags/my_custom_tag/domains

# Get a list of tags on domain
curl localhost:8080/domains/boo.kee/tags

# Get value of tag on domain
curl localhost:8080/domains/boo.kee/tags/my_custom_tag
