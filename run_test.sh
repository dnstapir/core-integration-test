#!/bin/bash

echo "### Setting up tests..."
docker compose -f sut/docker-compose.yaml up -d

echo "### Running tests..."
pytest
echo "### Done running tests!"

docker compose -f sut/docker-compose.yaml stop
