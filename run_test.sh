#!/bin/bash

echo "### Setting up tests..."
docker compose -f sut/docker-compose.yaml up

echo "### Running tests..."
pytest
echo "### Done running tests!"
