/* SPDX-License-Identifier: GPL-3.0-only */
#ifndef VIRTUAL_TOUCHPAD_H
#define VIRTUAL_TOUCHPAD_H
#include "evdev_api.h"
#define MAX_SLOTS 64
struct profile {
    int width, touch, edge_width, edge_percent;
};
struct contact {
    int id;
    int axes[ABS_CNT];
};
struct frame {
    int nslots, button;
    struct contact slots[MAX_SLOTS];
    unsigned char lifted[MAX_SLOTS];
};
struct filter {
    int ids[MAX_SLOTS];
    int locked, block_button;
    int (*cancel_gestures)(void *);
    void *cancel_data;
};
typedef int (*event_writer)(void *, unsigned int, unsigned int, int);
int profile_read(const char *path, struct profile *p);
int palm_candidate(const struct frame *f, const struct profile *p,
                   const struct input_absinfo *x);
void filter_init(struct filter *f);
int filter_frame(struct filter *f, const struct frame *frame,
                 const struct profile *profile, const struct input_absinfo *x,
                 const unsigned char supported[ABS_CNT], event_writer write_event,
                 void *userdata);
int virtual_touchpad_create(struct libevdev *dev, char *path, unsigned int size);
int virtual_touchpad_ready(const char *path);
int virtual_touchpad_write(void *fd, unsigned int type, unsigned int code, int value);
void virtual_touchpad_destroy(int fd);
#endif
