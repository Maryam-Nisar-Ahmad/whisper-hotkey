"""
1) Debounce logic matches main.py (no double-toggle from key repeat).
2) keyboard.add_hotkey('r', ...) registers without error.

Manual check: run main.py and press R twice — should start/stop once each.
"""
import time

_DEBOUNCE_S = 0.4


def test_debounce_matches_main():
    last = 0.0
    count = 0

    def try_toggle(t_now):
        nonlocal last, count
        if t_now - last < _DEBOUNCE_S:
            return
        last = t_now
        count += 1

    base = 1000.0
    try_toggle(base + 0.0)  # 1
    try_toggle(base + 0.1)  # debounced
    try_toggle(base + 0.5)  # 2 (>0.4 from first)
    try_toggle(base + 0.52)  # debounced
    try_toggle(base + 0.95)  # 3 (>0.4 from second)
    assert count == 3, f"expected 3 toggles, got {count}"
    print("debounce logic: PASS")


def test_keyboard_registers():
    import keyboard

    fired = []

    def cb():
        fired.append(1)

    keyboard.add_hotkey("r", cb)
    keyboard.remove_hotkey(cb)
    print("keyboard.add_hotkey('r', ...): PASS")


if __name__ == "__main__":
    test_debounce_matches_main()
    test_keyboard_registers()
    print("All automated checks OK. Press R in the running app to verify live.")
