import time
from contextlib import contextmanager

import docker

from bitbucket_listener import MongoDataAccess
from process_context import find_free_port

class ManagedContainer:
    def __init__(self, container) -> None:
        self.container = container

@contextmanager
def managed_container( *args, **kwargs ):
    client = docker.from_env()
    client.ping()
    container = None
    try:
        container = client.containers.run(*args, detach=True, remove=True, **kwargs)
        while container.status != "running":
            time.sleep(1)
            container = client.containers.get(container.id)
        # TODO: wait for the container to start
        yield ManagedContainer(container)
    finally:
        if container is not None:
            container.kill()

class ManagedMongo(ManagedContainer):
    def __init__(self, container, mongo_port):
        super().__init__(container)
        self.mongo_port = mongo_port

@contextmanager
def managed_mongo():
    mongo_port = find_free_port()
    with managed_container("mongo", ports={'27017/tcp': mongo_port} ) as container:
        while True:
            try:
                MongoDataAccess(f"mongodb://127.0.0.1:{mongo_port}/bitbucket")
                break
            except Exception:
                time.sleep(1)
        yield ManagedMongo(container.container, mongo_port)
