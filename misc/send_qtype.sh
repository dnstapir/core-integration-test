#!/bin/bash

timestamp=$(date -Iseconds -u)

qname="${1:-foo.bar}"
qtype="${2:-1}"
edgeid="1"
event_bus="core-integration-test.events.new_qname"

# sending queries below threshold
event_msg="{
  \"flags\": 33155,
  \"qclass\": 1,
  \"qname\": \"$qname\",
  \"qtype\": $qtype,
  \"timestamp\": \"${timestamp}\",
  \"type\": \"new_qname\",
  \"version\": 0
}"
    
nats pub -H "DNSTAPIR-Key-Thumbprint: edge-${edgeid}" $event_bus "${event_msg}"

