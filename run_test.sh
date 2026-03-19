#!/bin/bash

echo "### Clearing out old containers..."
docker compose -f sut/docker-compose.yaml rm -f

echo "### Setting up test containers..."
docker compose -f sut/docker-compose.yaml up -d

echo "### Running tests..."
pytest
echo "### Done running tests!"

echo "### Shutting down test containers..."
docker compose -f sut/docker-compose.yaml stop

echo "### Clearing out test containers..."
docker compose -f sut/docker-compose.yaml rm -f
