.PHONY: start-kitt kill-agents

kill-agents:
	@echo "Killing all agents..."
	@pgrep -f 'agent.py' | grep -v grep | grep -v make | xargs -r kill -9
	@sleep 1
	@echo "Checking for remaining instances of agent..."

start-kitt:
	nohup python kitt-plus/agent.py start >> kitt.log 2>&1 &

start-avatar:
	nohup python ai-avatar/agent.py start >> avatar.log 2>&1 &

.PHONY: format
format:
	black .
	isort .
