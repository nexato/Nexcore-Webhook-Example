"""State store tests: idempotency + subscription persistence."""

from pathlib import Path

from app.store import Store, SubscriptionState


def test_mark_event_processed_is_idempotent(tmp_path: Path) -> None:
    store = Store(tmp_path / "state.sqlite")
    # First claim wins, second is a duplicate.
    assert store.mark_event_processed("evt-1") is True
    assert store.mark_event_processed("evt-1") is False
    assert store.is_event_processed("evt-1") is True
    assert store.is_event_processed("evt-unknown") is False


def test_duplicate_event_processed_only_once(tmp_path: Path) -> None:
    store = Store(tmp_path / "state.sqlite")
    processed_count = 0
    for _ in range(5):  # same event delivered 5 times
        if store.mark_event_processed("evt-dup"):
            processed_count += 1
    assert processed_count == 1


def test_unmark_event_releases_claim(tmp_path: Path) -> None:
    store = Store(tmp_path / "state.sqlite")
    assert store.mark_event_processed("evt-1") is True
    store.unmark_event_processed("evt-1")
    assert store.is_event_processed("evt-1") is False
    # after release, it can be claimed again
    assert store.mark_event_processed("evt-1") is True
    store.unmark_event_processed("nonexistent")  # no-op, must not raise


def test_subscription_roundtrip_and_upsert(tmp_path: Path) -> None:
    store = Store(tmp_path / "state.sqlite")
    assert store.get_subscription("ext-1") is None

    store.save_subscription("ext-1", subscription_id=None, secret="s1")
    assert store.get_subscription("ext-1") == SubscriptionState("ext-1", None, "s1")

    # Upsert with server id + rotated secret.
    store.save_subscription("ext-1", subscription_id="uuid-123", secret="s2")
    assert store.get_subscription("ext-1") == SubscriptionState("ext-1", "uuid-123", "s2")


def test_delete_subscription(tmp_path: Path) -> None:
    store = Store(tmp_path / "state.sqlite")
    store.save_subscription("ext-1", "uuid-1", "secret")
    store.delete_subscription("ext-1")
    assert store.get_subscription("ext-1") is None


def test_state_survives_restart(tmp_path: Path) -> None:
    db = tmp_path / "state.sqlite"
    store1 = Store(db)
    store1.mark_event_processed("evt-persist")
    store1.save_subscription("ext-persist", "uuid-9", "topsecret")

    # New Store instance against the same file = simulated restart.
    store2 = Store(db)
    assert store2.is_event_processed("evt-persist") is True
    assert store2.get_subscription("ext-persist") == SubscriptionState(
        "ext-persist", "uuid-9", "topsecret"
    )


def test_creates_parent_directory(tmp_path: Path) -> None:
    nested = tmp_path / "a" / "b" / "state.sqlite"
    Store(nested)  # must not raise
    assert nested.parent.is_dir()
