/* SPDX-License-Identifier: GPL-3.0-only */
#ifndef EVDEV_API_H
#define EVDEV_API_H
/* Prefer upstream headers. The fallback declares only the stable libevdev 1.x
 * public ABI we use, so Fedora's runtime package is sufficient for a local build.
 * No implementation or private structures are copied here.
 * https://www.freedesktop.org/software/libevdev/doc/latest/ */
#if __has_include(<libevdev/libevdev.h>)
#include <libevdev/libevdev.h>
#else
#include <linux/input.h>
struct libevdev;
int libevdev_new_from_fd(int fd, struct libevdev **dev);
void libevdev_free(struct libevdev *dev);
int libevdev_next_event(struct libevdev *dev, unsigned int flags, struct input_event *ev);
int libevdev_has_event_code(const struct libevdev *dev, unsigned int type, unsigned int code);
int libevdev_has_event_type(const struct libevdev *dev, unsigned int type);
int libevdev_has_property(const struct libevdev *dev, unsigned int prop);
const struct input_absinfo *libevdev_get_abs_info(const struct libevdev *dev, unsigned int code);
int libevdev_get_num_slots(const struct libevdev *dev);
int libevdev_get_slot_value(const struct libevdev *dev, unsigned int slot, unsigned int code);
int libevdev_get_event_value(const struct libevdev *dev, unsigned int type, unsigned int code);
int libevdev_get_id_vendor(const struct libevdev *dev);
int libevdev_get_id_product(const struct libevdev *dev);
int libevdev_get_id_bustype(const struct libevdev *dev);
const char *libevdev_get_name(const struct libevdev *dev);
const char *libevdev_get_phys(const struct libevdev *dev);
#define LIBEVDEV_READ_FLAG_SYNC 1
#define LIBEVDEV_READ_FLAG_NORMAL 2
#define LIBEVDEV_READ_FLAG_FORCE_SYNC 4
#define LIBEVDEV_READ_STATUS_SYNC 1
#endif
#endif
