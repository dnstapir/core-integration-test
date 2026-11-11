#!/bin/bash

KEY=$(openssl rand -hex 32)
echo "key (give to user): $KEY"
echo "[[api_users]]"
echo "name = \"alice\""
SHA=$(printf '%s' "$KEY" | sha256sum | cut -d' ' -f1)
echo "key_sha256 = \"$SHA\""
