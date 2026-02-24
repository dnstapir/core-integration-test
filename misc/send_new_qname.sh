#!/bin/bash

timestamp=$(date -Iseconds -u)

event_msg="{
  \"flags\": 33155,
  \"qclass\": 1,
  \"qname\": \"$1\",
  \"qtype\": 28,
  \"timestamp\": \"${timestamp}\",
  \"type\": \"new_qname\",
  \"version\": 0
}"

nats pub -H "DNSTAPIR-Key-Thumbprint: $3" $2 "${event_msg}"
