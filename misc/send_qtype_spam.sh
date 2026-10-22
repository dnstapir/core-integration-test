#!/bin/bash

set -euo pipefail

if [[ $# -ne 1 || ! $1 =~ ^[0-9]+$ ]]; then
    echo "Usage: $0 <number_of_queries>" >&2
    exit 1
fi

edgeid="1"
event_bus="core-integration-test.events.new_qname"

send () {
    event_msg="{
      \"flags\": 33155,
      \"qclass\": 1,
      \"qname\": \"$1\",
      \"qtype\": $2,
      \"timestamp\": \"$(date -Iseconds -u)\",
      \"type\": \"new_qname\",
      \"version\": 0
    }"
        
    nats pub -H "DNSTAPIR-Key-Thumbprint: edge-${edgeid}" $event_bus "${event_msg}"
}

qtypes=(1 2 5 15 16 28)   # A NS CNAME MX TXT AAAA

declare -A weights=(
    [foo.se]="60  0  10  10  5  15"
    [boo.se]="65  0  10   5  5  15"
    [kee.se]="55  5  10  10  5  15"
    [bar.se]=" 5  0   0   0 90   5"
    [baz.se]="10 10   0   0 70  10"
)

domains=("${!weights[@]}")

pick_qtype() {
    local -a w
    read -ra w <<< "${weights[$1]}"

    local total=0 x
    for x in "${w[@]}"; do (( total += x )); done
    (( total > 0 )) || { echo "Error: weights for $1 sum to 0" >&2; exit 1; }

    # 30-bit random number (RANDOM alone is only 15 bits)
    local r=$(( ((RANDOM << 15) | RANDOM) % total ))
    local i
    for i in "${!w[@]}"; do
        if (( r < w[i] )); then
            echo "${qtypes[i]}"
            return
        fi
        (( r -= w[i] ))
    done
}

for ((i = 0; i < $1; i++)); do
    domain=${domains[RANDOM % ${#domains[@]}]}
    qtype=$(pick_qtype "$domain")
    send $domain $qtype
done
