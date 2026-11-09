#!/bin/bash

APIKEY="TEST_KEY"

send () {
    curl -i -X POST "localhost:8080/domains/$1/tags/$2" \
        -H "Content-Type: application/json" \
        --header "X-API-Key: $APIKEY" \
        -d "$(printf '{"value": "%s"}' "$3")"
}

tags=(
    "internal_testing"
    "anomalous_qtype_distribution"
    "my_custom_tag"
)

domain="foo.bar"
value="foobookee"
for tag in "${tags[@]}"; do
    send $domain $tag $value
done

send "boo.kee" "my_custom_tag" "test"
send "boo.kee" "anomalous_qtype_distribution" "test"

curl -i -X POST "localhost:8080/domains/foo.bar/tags/missing-body" --header "X-API-Key: $APIKEY"
