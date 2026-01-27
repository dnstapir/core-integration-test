#!/bin/bash

echo "### Setting up tests..."
mkdir -p WORK
touch WORK/dummy
echo "### Done setting up tests!"

echo "### Running tests..."
pytest
echo "### Done running tests!"
