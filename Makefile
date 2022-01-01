APP_VERSION=0.2.0

build:
	docker build --tag denaro/denaro:$(APP_VERSION) .

destroy:
	docker container rm denaro-node
	docker image rm denaro/denaro:$(APP_VERSION)