from importlib import import_module
from celery import shared_task


@shared_task
def call(path, *args):
    mod, fn = path.rsplit(":", 1)
    return getattr(import_module(mod), fn)(*args)
