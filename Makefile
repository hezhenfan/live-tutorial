.PHONY: start-agent start-agent

kill-agents:
	@echo "Killing all agents..."
	@pgrep -f 'agent.py' | grep -v grep | grep -v make | xargs -r kill -9
	@sleep 1
	@echo "Checking for remaining instances of agent..."

start-agent:
	nohup python agent.py start &

.PHONY: format
format:
	black .
	isort .
