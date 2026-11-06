// SPDX-License-Identifier: GPL-3.0-only
// Copyright (C) 2026 Ryan C.
#define _GNU_SOURCE
#include "virtual_touchpad.h"
#include <errno.h>
#include <fcntl.h>
#include <libinput.h>
#include <linux/uinput.h>
#include <poll.h>
#include <stdio.h>
#include <string.h>
#include <sys/ioctl.h>
#include <unistd.h>

int virtual_touchpad_write(void *data, unsigned int type, unsigned int code, int value)
{
    int fd = *(int *)data;
    struct input_event ev = {.type = type, .code = code, .value = value};
    /* One event write is atomic; partial writes are failures. Bound backpressure. */
    for (int tries = 0; tries < 3; tries++) {
        ssize_t n = write(fd, &ev, sizeof(ev));
        if (n == sizeof(ev)) return 0;
        if (n < 0 && errno == EINTR) continue;
        if (n < 0 && errno == EAGAIN) {
            struct pollfd p = {.fd = fd, .events = POLLOUT};
            if (poll(&p, 1, 20) >= 0) continue;
        }
        return -1;
    }
    return -1;
}

int virtual_touchpad_create(struct libevdev *dev, char *path, unsigned int size)
{
    int fd = open("/dev/uinput", O_WRONLY | O_NONBLOCK | O_CLOEXEC);
    if (fd < 0) return -1;
    if (ioctl(fd, UI_SET_PROPBIT, INPUT_PROP_POINTER) < 0 ||
        ioctl(fd, UI_SET_PROPBIT, INPUT_PROP_BUTTONPAD) < 0 ||
        ioctl(fd, UI_SET_EVBIT, EV_KEY) < 0 || ioctl(fd, UI_SET_EVBIT, EV_ABS) < 0) goto fail;
    const int keys[] = {BTN_LEFT, BTN_TOUCH, BTN_TOOL_FINGER, BTN_TOOL_DOUBLETAP,
                        BTN_TOOL_TRIPLETAP, BTN_TOOL_QUADTAP, BTN_TOOL_QUINTTAP};
    for (unsigned int i = 0; i < sizeof(keys)/sizeof(keys[0]); i++)
        if (ioctl(fd, UI_SET_KEYBIT, keys[i]) < 0) goto fail;
    for (unsigned int axis = 0; axis < ABS_CNT; axis++) {
        const struct input_absinfo *info = libevdev_get_abs_info(dev, axis);
        if (!info) continue;
        struct uinput_abs_setup setup = {.code = axis, .absinfo = *info};
        setup.absinfo.value = 0;
        if (ioctl(fd, UI_SET_ABSBIT, axis) < 0 || ioctl(fd, UI_ABS_SETUP, &setup) < 0) goto fail;
    }
    struct uinput_setup setup = {0};
    snprintf(setup.name, sizeof(setup.name), "PalmReject MacBookPro16,1 Touchpad");
    setup.id.bustype = BUS_VIRTUAL;
    setup.id.vendor = 0x05ac;
    setup.id.product = 0x0340;
    setup.id.version = 1;
    if (ioctl(fd, UI_DEV_SETUP, &setup) < 0 || ioctl(fd, UI_DEV_CREATE) < 0) goto fail;
    char sysname[128] = {0};
    if (ioctl(fd, UI_GET_SYSNAME(sizeof(sysname)), sysname) < 0) goto fail;
    int n = snprintf(path, size, "/sys/devices/virtual/input/%s", sysname);
    if (n < 0 || (unsigned int)n >= size) goto fail;
    return fd;
fail:
    close(fd); /* Also destroys a device if creation already succeeded. */
    return -1;
}

static int restricted_open(const char *path, int flags, void *data)
{
    if (strcmp(path, data)) return -EPERM;
    int fd = open(path, flags | O_CLOEXEC);
    return fd < 0 ? -errno : fd;
}
static void restricted_close(int fd, void *data) { (void)data; close(fd); }

int virtual_touchpad_ready(const char *path)
{
    /* libinput's path backend uses udev and verifies actual touchpad recognition.
     * The callback permits only this virtual device; keyboards are never opened. */
    const struct libinput_interface iface = {restricted_open, restricted_close};
    struct libinput *ctx = libinput_path_create_context(&iface, (void *)path);
    if (!ctx) return 0;
    struct libinput_device *dev = libinput_path_add_device(ctx, path);
    int ready = dev && libinput_device_has_capability(dev, LIBINPUT_DEVICE_CAP_POINTER) &&
                libinput_device_config_tap_get_finger_count(dev) > 0;
    if (dev) libinput_path_remove_device(dev);
    libinput_unref(ctx);
    return ready;
}

void virtual_touchpad_destroy(int fd)
{
    if (fd >= 0) { ioctl(fd, UI_DEV_DESTROY); close(fd); }
}
