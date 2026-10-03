"""Acceptance check for the cosmic-batchref task.

This file lives OUTSIDE the agent's workspace. The sandbox mounts it read-only
at /acceptance, so the agent can neither see it nor change it to make it pass.

It only uses the app's public parts (bootstrap, commands, message bus,
handlers), so any reasonable fix passes; it doesn't demand one specific
implementation. It also brings its own fakes instead of importing them from
the repo's tests/unit/, because the agent is allowed to edit that folder.

On the starting code, test_unknown_batch_ref_raises fails (handlers has no
InvalidBatchRef yet, and the handler crashes with AttributeError).
"""

import pytest
from allocation import bootstrap
from allocation.adapters import notifications, repository
from allocation.domain import commands
from allocation.service_layer import handlers, unit_of_work


class FakeRepository(repository.AbstractRepository):
    def __init__(self):
        super().__init__()
        self._products = set()

    def _add(self, product):
        self._products.add(product)

    def _get(self, sku):
        return next((p for p in self._products if p.sku == sku), None)

    def _get_by_batchref(self, batchref):
        return next(
            (p for p in self._products for b in p.batches if b.reference == batchref),
            None,
        )


class FakeUnitOfWork(unit_of_work.AbstractUnitOfWork):
    def __init__(self):
        self.products = FakeRepository()
        self.committed = False

    def _commit(self):
        self.committed = True

    def rollback(self):
        pass


class FakeNotifications(notifications.AbstractNotifications):
    def send(self, destination, message):
        pass


def make_bus():
    uow = FakeUnitOfWork()
    bus = bootstrap.bootstrap(
        start_orm=False, uow=uow, notifications=FakeNotifications(),
        publish=lambda *args: None,
    )
    return bus, uow


def test_unknown_batch_ref_raises():
    bus, uow = make_bus()
    bus.handle(commands.CreateBatch("b1", "SMALL-TABLE", 20, None))
    uow.committed = False

    with pytest.raises(handlers.InvalidBatchRef, match="Invalid batch ref no-such-batch"):
        bus.handle(commands.ChangeBatchQuantity("no-such-batch", 10))
    assert not uow.committed


def test_known_batch_still_changes_quantity():
    bus, uow = make_bus()
    bus.handle(commands.CreateBatch("b1", "SMALL-TABLE", 20, None))
    bus.handle(commands.ChangeBatchQuantity("b1", 5))

    [batch] = uow.products.get("SMALL-TABLE").batches
    assert batch.available_quantity == 5
