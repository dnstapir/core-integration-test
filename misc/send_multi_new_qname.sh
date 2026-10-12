#!/bin/bash

timestamp=$(date -Iseconds -u)

sld="multi.se"
event_bus="core-integration-test.events.new_qname"

# sending queries below threshold
qname="no-${sld}"
event_msg="{
  \"flags\": 33155,
  \"qclass\": 1,
  \"qname\": \"$qname\",
  \"qtype\": 28,
  \"timestamp\": \"${timestamp}\",
  \"type\": \"new_qname\",
  \"version\": 0
}"
for i in {1..3}
do
    nats pub -H "DNSTAPIR-Key-Thumbprint: edge-${i}" $event_bus "${event_msg}"
done

# sending queries above threshold
qname="yes-${sld}"
event_msg="{
  \"flags\": 33155,
  \"qclass\": 1,
  \"qname\": \"$qname\",
  \"qtype\": 28,
  \"timestamp\": \"${timestamp}\",
  \"type\": \"new_qname\",
  \"version\": 0
}"
for i in {1..4}
do
    nats pub -H "DNSTAPIR-Key-Thumbprint: edge-${i}" $event_bus "${event_msg}"
done

# sending queries outside window using delay
qname="delay-${sld}"
event_msg="{
  \"flags\": 33155,
  \"qclass\": 1,
  \"qname\": \"$qname\",
  \"qtype\": 28,
  \"timestamp\": \"${timestamp}\",
  \"type\": \"new_qname\",
  \"version\": 0
}"
for i in {1..4}
do
    if [ "$i" == "2" ]; then
        sleep 12 
    fi
    nats pub -H "DNSTAPIR-Key-Thumbprint: edge-${i}" $event_bus "${event_msg}"
done

# sending multiple queries from a single edge
qname="dupes-${sld}"
event_msg="{
  \"flags\": 33155,
  \"qclass\": 1,
  \"qname\": \"$qname\",
  \"qtype\": 28,
  \"timestamp\": \"${timestamp}\",
  \"type\": \"new_qname\",
  \"version\": 0
}"
for i in {1..4}
do
    nats pub -H "DNSTAPIR-Key-Thumbprint: edge-1" $event_bus "${event_msg}"
done

