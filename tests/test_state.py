from __future__ import annotations

import pytest

from audiohub.state import (
    TRANSITIONS,
    DeviceState,
    DeviceStateMachine,
    InvalidTransition,
)


def test_state_transition_happy_path():
    m = DeviceStateMachine("dev")
    assert m.state is DeviceState.DISCOVERED
    for nxt in (
        DeviceState.PAIRED,
        DeviceState.CONNECTING,
        DeviceState.CONNECTED,
        DeviceState.PLAYING,
    ):
        m.transition_to(nxt, "test")
    assert m.state is DeviceState.PLAYING
    assert m.is_live


def test_state_transition_illegal_is_rejected():
    m = DeviceStateMachine("dev")
    with pytest.raises(InvalidTransition):
        m.transition_to(DeviceState.PLAYING)
    assert m.state is DeviceState.DISCOVERED, "a rejected move must not mutate state"


def test_transition_to_same_state_is_a_noop():
    """Polling a backend that reports the same state twice is normal."""
    m = DeviceStateMachine("dev")
    m.transition_to(DeviceState.DISCOVERED)
    assert m.history == []


def test_force_bypasses_validation_for_os_ground_truth():
    m = DeviceStateMachine("dev")
    m.force(DeviceState.PLAYING, "OS says so")
    assert m.state is DeviceState.PLAYING
    assert m.last_reason() == "OS says so"


def test_disconnect_then_reconnect_cycle():
    m = DeviceStateMachine("dev", DeviceState.CONNECTED)
    m.transition_to(DeviceState.DISCONNECTED, "headphone slept")
    assert m.is_recoverable
    m.transition_to(DeviceState.RECONNECTING, "auto")
    m.transition_to(DeviceState.CONNECTED, "back")
    assert m.is_live


def test_failure_count_accumulates_and_resets():
    m = DeviceStateMachine("dev", DeviceState.CONNECTING)
    m.transition_to(DeviceState.FAILED, "1")
    m.transition_to(DeviceState.RECONNECTING, "retry")
    m.transition_to(DeviceState.FAILED, "2")
    assert m.failure_count == 2
    m.transition_to(DeviceState.CONNECTING, "retry")
    m.transition_to(DeviceState.CONNECTED, "ok")
    assert m.failure_count == 0, "a success must clear the failure streak"


def test_every_state_can_reach_a_failure_path():
    """No state may be a dead end -- Bluetooth can fail from anywhere."""
    for state, allowed in TRANSITIONS.items():
        assert allowed, f"{state} has no outgoing transitions"
        if state is not DeviceState.FAILED:
            assert (
                DeviceState.FAILED in allowed or DeviceState.DISCONNECTED in allowed
            ), f"{state} cannot express failure"


def test_history_records_transitions_in_order():
    clock = iter([1.0, 2.0, 3.0])
    m = DeviceStateMachine("dev", clock=lambda: next(clock))
    m.transition_to(DeviceState.PAIRED, "a")
    m.transition_to(DeviceState.CONNECTING, "b")
    assert [r.reason for r in m.history] == ["a", "b"]
    assert [r.at for r in m.history] == [1.0, 2.0]
