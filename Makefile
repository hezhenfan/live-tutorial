.PHONY: agent

livekit-server:
	@echo "Killing livekit server listening on port 7880..."
	@-pkill -f 'livekit-server' || true
	nohup livekit-server --dev &

agent: livekit-server
	python agent.py start --log-level=INFO

.PHONY: format
format:
	black .
	isort .