DEV_SERVER=awooga.local
deploy:
	rsync -vr --exclude *.pyc custom_components/fossibot_ble $(DEV_SERVER):/var/homeassistant/custom_components

restart-docker:
	ssh awooga.local docker restart homeassistant
