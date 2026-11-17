#ifndef STUDPAD_INPUT_BRIDGE_H
#define STUDPAD_INPUT_BRIDGE_H

/* AppKit event type values used by the UIKit-to-Qt input bridge. */
enum {
    STUDPAD_EVENT_LEFT_MOUSE_DOWN = 1,
    STUDPAD_EVENT_LEFT_MOUSE_UP = 2,
    STUDPAD_EVENT_MOUSE_MOVED = 5,
    STUDPAD_EVENT_LEFT_MOUSE_DRAGGED = 6,
    STUDPAD_EVENT_KEY_DOWN = 10,
    STUDPAD_EVENT_KEY_UP = 11,
    STUDPAD_EVENT_FLAGS_CHANGED = 12,
    STUDPAD_EVENT_SCROLL_WHEEL = 22
};

enum {
    STUDPAD_TOUCH_BEGAN = 0,
    STUDPAD_TOUCH_MOVED = 1,
    STUDPAD_TOUCH_ENDED = 2,
    STUDPAD_TOUCH_CANCELLED = 3
};

static inline long studpad_mouse_event_for_touch_phase(int phase) {
    switch (phase) {
        case STUDPAD_TOUCH_BEGAN:
            return STUDPAD_EVENT_LEFT_MOUSE_DOWN;
        case STUDPAD_TOUCH_MOVED:
            return STUDPAD_EVENT_LEFT_MOUSE_DRAGGED;
        case STUDPAD_TOUCH_ENDED:
        case STUDPAD_TOUCH_CANCELLED:
            return STUDPAD_EVENT_LEFT_MOUSE_UP;
        default:
            return -1;
    }
}

static inline int studpad_hid_usage_is_modifier(unsigned short hid) {
    return hid >= 0xE0 && hid <= 0xE7;
}

static inline long studpad_key_event_for_hid(unsigned short hid, int down) {
    if (studpad_hid_usage_is_modifier(hid)) return STUDPAD_EVENT_FLAGS_CHANGED;
    return down ? STUDPAD_EVENT_KEY_DOWN : STUDPAD_EVENT_KEY_UP;
}

/* USB HID keyboard usage to the macOS virtual keycode used by NSEvent. */
static inline unsigned short studpad_mac_keycode_for_hid(unsigned short hid) {
    switch (hid) {
        case 0x04: return 0;   case 0x05: return 11;  case 0x06: return 8;   case 0x07: return 2;
        case 0x08: return 14;  case 0x09: return 3;   case 0x0A: return 5;   case 0x0B: return 4;
        case 0x0C: return 34;  case 0x0D: return 38;  case 0x0E: return 40;  case 0x0F: return 37;
        case 0x10: return 46;  case 0x11: return 45;  case 0x12: return 31;  case 0x13: return 35;
        case 0x14: return 12;  case 0x15: return 15;  case 0x16: return 1;   case 0x17: return 17;
        case 0x18: return 32;  case 0x19: return 9;   case 0x1A: return 13;  case 0x1B: return 7;
        case 0x1C: return 16;  case 0x1D: return 6;
        case 0x1E: return 18;  case 0x1F: return 19;  case 0x20: return 20;  case 0x21: return 21;
        case 0x22: return 23;  case 0x23: return 22;  case 0x24: return 26;  case 0x25: return 28;
        case 0x26: return 25;  case 0x27: return 29;
        case 0x28: return 36;  case 0x29: return 53;  case 0x2A: return 51;  case 0x2B: return 48;
        case 0x2C: return 49;  case 0x2D: return 27;  case 0x2E: return 24;  case 0x2F: return 33;
        case 0x30: return 30;  case 0x31: return 42;  case 0x33: return 41;  case 0x34: return 39;
        case 0x35: return 50;  case 0x36: return 43;  case 0x37: return 47;  case 0x38: return 44;
        case 0x3A: return 122; case 0x3B: return 120; case 0x3C: return 99;  case 0x3D: return 118;
        case 0x3E: return 96;  case 0x3F: return 97;  case 0x40: return 98;  case 0x41: return 100;
        case 0x42: return 101; case 0x43: return 109; case 0x44: return 103; case 0x45: return 111;
        case 0x49: return 115; case 0x4A: return 116; case 0x4B: return 119; case 0x4C: return 117;
        case 0x4D: return 121; case 0x4E: return 92;  case 0x4F: return 124; case 0x50: return 123;
        case 0x51: return 125; case 0x52: return 126;
        case 0xE0: return 59;  case 0xE1: return 56;  case 0xE2: return 58;  case 0xE3: return 55;
        case 0xE4: return 62;  case 0xE5: return 60;  case 0xE6: return 61;  case 0xE7: return 54;
        default: return 0xFFFF;
    }
}

#endif

