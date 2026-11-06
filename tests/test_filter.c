/* SPDX-License-Identifier: GPL-3.0-only */
#define _GNU_SOURCE
#include "virtual_touchpad.h"
#include <assert.h>
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

struct output {
    int calls, fail_at, button, touches, pressure, zero_width, minor, orientation, slot, ids[MAX_SLOTS];
};
static int record(void *data, unsigned int type, unsigned int code, int value)
{
    struct output *o = data;
    if (++o->calls == o->fail_at) return -1;
    if (type == EV_KEY && code == BTN_LEFT) o->button = value;
    if (type == EV_KEY && code == BTN_TOUCH) o->touches = value;
    if (type == EV_ABS && code == ABS_MT_WIDTH_MINOR) o->minor = value;
    if (type == EV_ABS && code == ABS_MT_ORIENTATION) o->orientation = value;
    if (type == EV_ABS && code == ABS_MT_SLOT) o->slot = value;
    if (type == EV_ABS && code == ABS_MT_TRACKING_ID) o->ids[o->slot] = value;
    if (type == EV_ABS && (code == ABS_MT_PRESSURE || code == ABS_PRESSURE)) o->pressure++;
    if (type == EV_ABS && code == ABS_MT_WIDTH_MAJOR && value == 0) o->zero_width++;
    return 0;
}
static struct frame empty_frame(void)
{
    struct frame f = {.nslots = 16};
    for (int i = 0; i < f.nslots; i++) f.slots[i].id = -1;
    return f;
}
static const struct profile profile = {3000, 1000, 2000, 10};
static const struct input_absinfo x = {.minimum = -8000, .maximum = 8000, .resolution = 100};
static unsigned char supported[ABS_CNT];
static int render(struct filter *state, struct frame *frame, struct output *o, int filtering)
{
    return filter_frame(state, frame, filtering ? &profile : NULL, &x, supported, record, o);
}
static void test_shapes(void)
{
    struct frame f = empty_frame();
    f.slots[0].id = 42;
    f.slots[0].axes[ABS_MT_WIDTH_MAJOR] = 1999;
    f.slots[0].axes[ABS_MT_POSITION_X] = -7900;
    assert(!palm_candidate(&f, &profile, &x));
    f.slots[0].axes[ABS_MT_WIDTH_MAJOR] = 2001;
    assert(palm_candidate(&f, &profile, &x));
    f.slots[0].axes[ABS_MT_POSITION_X] = 0;
    assert(!palm_candidate(&f, &profile, &x));
    f.slots[0].axes[ABS_MT_TOUCH_MAJOR] = 1001;
    assert(palm_candidate(&f, &profile, &x));
    f.slots[0].id = -1;
    assert(!palm_candidate(&f, &profile, &x));
}
static void test_frames(void)
{
    struct filter state;
    filter_init(&state);
    struct frame f = empty_frame();
    struct output o = {0};
    f.slots[3].id = 100; f.button = 1;
    f.slots[3].axes[ABS_MT_WIDTH_MINOR] = 71;
    f.slots[3].axes[ABS_MT_ORIENTATION] = -123;
    assert(!render(&state, &f, &o, 1));
    assert(o.touches == 1 && o.button == 1 && o.ids[3] == 100);
    assert(o.minor == 71 && o.orientation == -123);
    assert(o.pressure == 0 && o.zero_width > 0); /* Preserve zero; omit pressure. */
    f.slots[3].axes[ABS_MT_WIDTH_MAJOR] = 4000;
    assert(!render(&state, &f, &o, 1));
    assert(o.touches == 0 && o.button == 0 && o.ids[3] == -1);
    f.slots[3].axes[ABS_MT_WIDTH_MAJOR] = 0;
    assert(!render(&state, &f, &o, 1));
    assert(o.touches == 0); /* Palm lock persists through shape changes. */
    f.slots[3].id = -1;
    assert(!render(&state, &f, &o, 1));
    assert(o.button == 0); /* No deferred button press while still physically down. */
    f.button = 0;
    assert(!render(&state, &f, &o, 1));
    f.slots[3].id = 101; f.button = 1;
    assert(!render(&state, &f, &o, 1));
    assert(o.touches == 1 && o.button == 1 && o.ids[3] == 101);
    f.slots[3].id = 102;
    assert(!render(&state, &f, &o, 1));
    assert(o.ids[3] == 102);
    /* Passthrough must never classify palm-shaped data. */
    f.slots[3].axes[ABS_MT_WIDTH_MAJOR] = 5000;
    assert(!render(&state, &f, &o, 0));
    assert(o.touches == 1);
    f = empty_frame();
    assert(!render(&state, &f, &o, 0));
    assert(o.button == 0 && o.ids[3] == -1 && o.touches == 0);
    f.nslots = MAX_SLOTS + 1;
    assert(render(&state, &f, &o, 0) == -1);
}
static void test_every_output_failure(void)
{
    struct frame f = empty_frame();
    f.slots[0].id = 23; f.slots[7].id = 91;
    struct filter state;
    struct output o = {0};
    filter_init(&state);
    assert(!render(&state, &f, &o, 0));
    int total = o.calls;
    for (int n = 1; n <= total; n++) {
        filter_init(&state);
        memset(&o, 0, sizeof(o)); o.fail_at = n;
        assert(render(&state, &f, &o, 0) == -1);
        assert(o.calls == n); /* Stop on first output failure. */
    }
}
static void test_profiles(void)
{
    const char *cases[] = {
        "width_threshold=3000\ntouch_threshold=1000\nedge_width_threshold=2000\nedge_percent=10\n",
        "width_threshold=$(touch /tmp/palmreject-test-unwanted)\n",
        "width_threshold=3000\ntouch_threshold=1000\nedge_width_threshold=2000\nedge_percent=26\n",
        "width_threshold=3\ntouch_threshold=1\nedge_width_threshold=2\nedge_percent=10\nedge_percent=10\n",
        "width_threshold=3\ntouch_threshold=1\nedge_width_threshold=4\nedge_percent=10\n",
        "width_threshold=999999999999999999999999999999999999999\n",
        "width_threshold=0\n", "width_threshold=-1\n", "unknown=1\n",
        "width_threshold=1;echo malicious\n", "# only comments\n"
    };
    for (unsigned int i = 0; i < sizeof(cases)/sizeof(cases[0]); i++) {
        char file[] = "/tmp/palmreject-profile-XXXXXX";
        int fd = mkstemp(file);
        assert(fd >= 0);
        assert(write(fd, cases[i], strlen(cases[i])) == (ssize_t)strlen(cases[i]));
        close(fd);
        struct profile p = {0};
        assert((profile_read(file, &p) == 0) == (i == 0));
        if (!i) assert(p.width == 3000 && p.edge_percent == 10);
        unlink(file);
    }
    struct profile p;
    assert(profile_read("/this-file-does-not-exist", &p) == -1);
}
int main(void)
{
    supported[ABS_X] = supported[ABS_Y] = supported[ABS_MT_POSITION_X] = 1;
    supported[ABS_MT_POSITION_Y] = supported[ABS_MT_TOUCH_MAJOR] = 1;
    supported[ABS_MT_WIDTH_MAJOR] = supported[ABS_MT_WIDTH_MINOR] = supported[ABS_MT_ORIENTATION] = 1;
    test_shapes(); test_frames(); test_every_output_failure(); test_profiles();
    puts("filter/config tests passed");
}
