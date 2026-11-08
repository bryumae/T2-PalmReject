/* SPDX-License-Identifier: GPL-3.0-only */
#include "virtual_touchpad.h"
#include <ctype.h>
#include <errno.h>
#include <limits.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

int profile_read(const char *path, struct profile *p)
{
    FILE *file = fopen(path, "re");
    char line[256];
    unsigned int seen = 0;
    struct profile result = {0};
    if (!file) return -1;
    while (fgets(line, sizeof(line), file)) {
        char *key = line, *end, *value;
        long number;
        while (isspace((unsigned char)*key)) key++;
        if (!*key || *key == '#') continue;
        if (!strchr(key, '\n') && !feof(file)) goto invalid;
        value = strchr(key, '=');
        if (!value) goto invalid;
        *value++ = 0;
        end = key + strlen(key);
        while (end > key && isspace((unsigned char)end[-1])) *--end = 0;
        while (isspace((unsigned char)*value)) value++;
        if (!isdigit((unsigned char)*value)) goto invalid;
        errno = 0;
        number = strtol(value, &end, 10);
        while (isspace((unsigned char)*end)) end++;
        if (*end || errno || number < 1 || number > 65535) goto invalid;
        unsigned int bit;
        int *field;
        if (!strcmp(key, "width_threshold")) { bit = 1; field = &result.width; }
        else if (!strcmp(key, "touch_threshold")) { bit = 2; field = &result.touch; }
        else if (!strcmp(key, "edge_width_threshold")) { bit = 4; field = &result.edge_width; }
        else if (!strcmp(key, "edge_percent")) { bit = 8; field = &result.edge_percent; }
        else goto invalid;
        if (seen & bit) goto invalid;
        seen |= bit;
        *field = (int)number;
    }
    if (ferror(file) || seen != 15 || result.edge_percent > 25 ||
        result.edge_width > result.width) goto invalid;
    fclose(file);
    *p = result;
    return 0;
invalid:
    fclose(file);
    errno = EINVAL;
    return -1;
}

int palm_candidate(const struct frame *f, const struct profile *p,
                   const struct input_absinfo *x)
{
    long long span = (long long)x->maximum - x->minimum;
    for (int i = 0; i < f->nslots; i++) {
        const struct contact *c = &f->slots[i];
        long long pos = (long long)c->axes[ABS_MT_POSITION_X] - x->minimum;
        int edge = pos * 100 < span * p->edge_percent ||
                   pos * 100 > span * (100 - p->edge_percent);
        if (c->id >= 0 && (c->axes[ABS_MT_WIDTH_MAJOR] > p->width ||
            c->axes[ABS_MT_TOUCH_MAJOR] > p->touch ||
            (edge && c->axes[ABS_MT_WIDTH_MAJOR] > p->edge_width))) return 1;
    }
    return 0;
}

void filter_init(struct filter *f)
{
    memset(f, 0, sizeof(*f));
    for (int i = 0; i < MAX_SLOTS; i++) f->ids[i] = -1;
}

#define EMIT(t, c, v) do { if (out(data, (t), (c), (v))) return -1; } while (0)
int filter_frame(struct filter *f, const struct frame *frame,
                 const struct profile *profile, const struct input_absinfo *x,
                 const unsigned char supported[ABS_CNT], event_writer out, void *data)
{
    if (frame->nslots < 1 || frame->nslots > MAX_SLOTS) return -1;
    int count = 0, first = -1;
    for (int i = 0; i < frame->nslots; i++) count += frame->slots[i].id >= 0;
    if (profile && palm_candidate(frame, profile, x)) {
        /* No liftoff or button output may precede the compositor's reset. */
        if (!f->locked && (!f->cancel_gestures || f->cancel_gestures(f->cancel_data)))
            return -1;
        f->locked = 1;
        f->block_button = 1;
    }
    int suppressed = f->locked;
    if (!count && !frame->button) f->locked = 0;
    if (!frame->button && !f->locked) f->block_button = 0;
    for (int i = 0; i < frame->nslots; i++) {
        const struct contact *c = &frame->slots[i];
        int id = suppressed ? -1 : c->id;
        EMIT(EV_ABS, ABS_MT_SLOT, i);
        if (frame->lifted[i] && f->ids[i] >= 0) {
            EMIT(EV_ABS, ABS_MT_TRACKING_ID, -1);
            f->ids[i] = -1;
        }
        if (f->ids[i] != id) {
            if (f->ids[i] >= 0) EMIT(EV_ABS, ABS_MT_TRACKING_ID, -1);
            if (id >= 0) EMIT(EV_ABS, ABS_MT_TRACKING_ID, id);
            f->ids[i] = id;
        }
        if (id < 0) continue;
        if (first < 0) first = i;
        for (int axis = ABS_MT_TOUCH_MAJOR; axis <= ABS_MT_TOOL_Y; axis++) {
            if (axis != ABS_MT_TRACKING_ID && supported[axis])
                EMIT(EV_ABS, axis, c->axes[axis]);
        }
    }
    if (suppressed) count = 0;
    if (first >= 0) {
        if (supported[ABS_X]) EMIT(EV_ABS, ABS_X, frame->slots[first].axes[ABS_MT_POSITION_X]);
        if (supported[ABS_Y]) EMIT(EV_ABS, ABS_Y, frame->slots[first].axes[ABS_MT_POSITION_Y]);
        if (supported[ABS_PRESSURE]) EMIT(EV_ABS, ABS_PRESSURE, frame->slots[first].axes[ABS_MT_PRESSURE]);
    } else if (supported[ABS_PRESSURE]) EMIT(EV_ABS, ABS_PRESSURE, 0);
    EMIT(EV_KEY, BTN_LEFT, !suppressed && !f->block_button && frame->button);
    EMIT(EV_KEY, BTN_TOUCH, count > 0);
    const int tools[] = {BTN_TOOL_FINGER, BTN_TOOL_DOUBLETAP, BTN_TOOL_TRIPLETAP,
                         BTN_TOOL_QUADTAP, BTN_TOOL_QUINTTAP};
    for (int i = 0; i < 5; i++) EMIT(EV_KEY, tools[i], i == 4 ? count >= 5 : count == i + 1);
    EMIT(EV_SYN, SYN_REPORT, 0);
    return 0;
}
