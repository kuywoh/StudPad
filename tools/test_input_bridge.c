#include "../shim/InputBridge.h"

#include <stdio.h>
#include <stdlib.h>

static void check(int condition, const char *message) {
    if (condition) return;
    fprintf(stderr, "input bridge test failed: %s\n", message);
    exit(1);
}

int main(void) {
    check(studpad_mouse_event_for_touch_phase(STUDPAD_TOUCH_BEGAN) ==
              STUDPAD_EVENT_LEFT_MOUSE_DOWN,
          "touch begin becomes left mouse down");
    check(studpad_mouse_event_for_touch_phase(STUDPAD_TOUCH_MOVED) ==
              STUDPAD_EVENT_LEFT_MOUSE_DRAGGED,
          "touch move becomes left mouse drag");
    check(studpad_mouse_event_for_touch_phase(STUDPAD_TOUCH_ENDED) ==
              STUDPAD_EVENT_LEFT_MOUSE_UP,
          "touch end becomes left mouse up");
    check(studpad_mouse_event_for_touch_phase(STUDPAD_TOUCH_CANCELLED) ==
              STUDPAD_EVENT_LEFT_MOUSE_UP,
          "cancelled touch releases the mouse button");
    check(studpad_mouse_event_for_touch_phase(99) == -1,
          "unknown touch phase is rejected");

    check(studpad_mac_keycode_for_hid(0x04) == 0, "HID A maps to macOS A");
    check(studpad_mac_keycode_for_hid(0x28) == 36, "HID Return maps to macOS Return");
    check(studpad_mac_keycode_for_hid(0x2A) == 51, "HID Backspace maps to macOS Delete");
    check(studpad_mac_keycode_for_hid(0xE0) == 59, "left Control maps to macOS Control");
    check(studpad_mac_keycode_for_hid(0xE7) == 54, "right Command maps to macOS Command");
    check(studpad_mac_keycode_for_hid(0xFFFF) == 0xFFFF, "unknown HID usage is rejected");

    check(studpad_key_event_for_hid(0x04, 1) == STUDPAD_EVENT_KEY_DOWN,
          "ordinary key press becomes key down");
    check(studpad_key_event_for_hid(0x04, 0) == STUDPAD_EVENT_KEY_UP,
          "ordinary key release becomes key up");
    check(studpad_key_event_for_hid(0xE1, 1) == STUDPAD_EVENT_FLAGS_CHANGED,
          "modifier press becomes flags changed");
    check(studpad_key_event_for_hid(0xE1, 0) == STUDPAD_EVENT_FLAGS_CHANGED,
          "modifier release becomes flags changed");
    check(!studpad_hid_usage_is_modifier(0x04), "letters are not modifiers");
    check(studpad_hid_usage_is_modifier(0xE7), "modifier HID usages are recognized");

    puts("input bridge tests passed");
    return 0;
}

