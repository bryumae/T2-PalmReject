/* SPDX-License-Identifier: GPL-3.0-only */
#define main palmreject_program_main
#include "../src/main.c"
#undef main
#include <assert.h>
/* Public libevdev device construction API, used only to model inputs offline. */
struct libevdev *libevdev_new(void);
int libevdev_enable_event_code(struct libevdev *, unsigned int, unsigned int, const void *);
int libevdev_set_slot_value(struct libevdev *, unsigned int, unsigned int, int);
int libevdev_set_event_value(struct libevdev *, unsigned int, unsigned int, int);
static int results[8], calls;
int __wrap_libevdev_next_event(struct libevdev *dev, unsigned int flags, struct input_event *event)
{
    (void)dev; (void)event;
    assert(flags == LIBEVDEV_READ_FLAG_SYNC || flags == LIBEVDEV_READ_FLAG_FORCE_SYNC);
    assert(calls < 8);
    return results[calls++];
}
static void axis(struct libevdev *dev, unsigned int code, int min, int max)
{
    struct input_absinfo a = {.minimum = min, .maximum = max, .resolution = 100};
    assert(libevdev_enable_event_code(dev, EV_ABS, code, &a) == 0);
}
int main(void)
{
    /* Announcing a sysfs-discovered node must not require access to /dev/input:
     * the launcher cannot allow it until it has received the announcement. */
    char directory[]="/tmp/palmreject-virtual-path-XXXXXX";
    assert(mkdtemp(directory));
    char child[PATH_MAX], discovered[PATH_MAX];
    assert(virtual_path(directory,discovered)==-1);
    snprintf(child,sizeof(child),"%s/event123456789",directory);
    assert(!mkdir(child,0700));
    assert(!virtual_path(directory,discovered));
    assert(!strcmp(discovered,"/dev/input/event123456789"));
    assert(!rmdir(child));
    assert(!rmdir(directory));
    struct libevdev *dev = libevdev_new();
    assert(dev);
    axis(dev, ABS_MT_SLOT, 0, 15);
    axis(dev, ABS_MT_TRACKING_ID, 0, 65535);
    axis(dev, ABS_MT_POSITION_X, -8000, 8000);
    axis(dev, ABS_MT_POSITION_Y, -6000, 100);
    axis(dev, ABS_MT_TOUCH_MAJOR, 0, 65535);
    axis(dev, ABS_MT_WIDTH_MAJOR, 0, 65535);
    assert(libevdev_enable_event_code(dev, EV_KEY, BTN_LEFT, NULL) == 0);
    for (int i = 0; i < 16; i++)
        assert(libevdev_set_slot_value(dev, i, ABS_MT_TRACKING_ID, -1) == 0);
    struct frame f;
    snapshot(dev, &f);
    assert(f.nslots == 16 && idle(&f) && frame_valid(dev, &f));
    assert(!libevdev_has_event_code(dev, EV_ABS, ABS_MT_PRESSURE));
    libevdev_set_slot_value(dev, 7, ABS_MT_TRACKING_ID, 42);
    libevdev_set_slot_value(dev, 7, ABS_MT_POSITION_X, 1234);
    libevdev_set_slot_value(dev, 7, ABS_MT_POSITION_Y, -500);
    libevdev_set_slot_value(dev, 7, ABS_MT_WIDTH_MAJOR, 0);
    snapshot(dev, &f);
    assert(!idle(&f) && f.slots[7].id == 42);
    assert(f.slots[7].axes[ABS_MT_POSITION_X] == 1234);
    assert(f.slots[7].axes[ABS_MT_WIDTH_MAJOR] == 0 && frame_valid(dev, &f));
    f.slots[7].axes[ABS_MT_POSITION_X] = 8001;
    assert(!frame_valid(dev, &f));
    f.slots[7].axes[ABS_MT_POSITION_X] = 0;
    f.slots[7].id = -2;
    assert(!frame_valid(dev, &f));
    libevdev_set_slot_value(dev, 7, ABS_MT_TRACKING_ID, -1);
    libevdev_set_event_value(dev, EV_KEY, BTN_LEFT, 1);
    snapshot(dev, &f);
    assert(!idle(&f));
    results[0] = results[1] = LIBEVDEV_READ_STATUS_SYNC;
    results[2] = -EAGAIN; calls = 0;
    assert(sync_device(dev, 0) == 0 && calls == 3);
    results[0] = LIBEVDEV_READ_STATUS_SYNC; results[1] = -EAGAIN; calls = 0;
    assert(sync_device(dev, 1) == 0 && calls == 2);
    results[0] = -ENODEV; calls = 0;
    assert(sync_device(dev, 0) == -1);
    calls = 0;
    assert(sync_device(dev, 1) == -1);
    results[0] = LIBEVDEV_READ_STATUS_SYNC; calls = 0; stopping = 1;
    assert(sync_device(dev, 0) == -1);
    stopping = 0;
    int fd = open("/dev/full", O_WRONLY | O_CLOEXEC);
    assert(fd >= 0);
    assert(virtual_touchpad_write(&fd, EV_SYN, SYN_REPORT, 0) == -1);
    close(fd);
    fd = -1;
    assert(virtual_touchpad_write(&fd, EV_SYN, SYN_REPORT, 0) == -1);
    libevdev_free(dev);
    puts("input snapshot/synchronization/output-failure tests passed");
}
