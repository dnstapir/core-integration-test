run:
	./run_test.sh

clean:
	-rm -rf WORK/
	-rm -rf __pycache__/
	-rm -rf .pytest_cache/
	-docker compose -f sut/docker-compose.yaml rm -f
