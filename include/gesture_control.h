/* SPDX-License-Identifier: GPL-3.0-only */
#ifndef GESTURE_CONTROL_H
#define GESTURE_CONTROL_H
#include <sys/types.h>
#include <stdint.h>
struct gesture_control { int fd; uint64_t sequence; };
int gesture_listen(const char *directory, gid_t group);
int gesture_accept(int listener, uid_t user, struct gesture_control *control, int timeout_ms);
int gesture_request(struct gesture_control *control, const char *operation,
                    const char *device, int timeout_ms);
int gesture_alive(const struct gesture_control *control);
#endif
