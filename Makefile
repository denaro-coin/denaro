APP_VERSION=0.2.0

build:
	docker build --tag denaro/denaro:$(APP_VERSION) .

destroy:
	docker container rm denaro-node
	docker image rm denaro/denaro:$(APP_VERSION)
	
run:
	docker container run -it --rm --publish 8080:80 --name az-frontend-react azinfo/az-frontend-react:$(APP_VERSION)