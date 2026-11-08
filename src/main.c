// SPDX-License-Identifier: GPL-3.0-only
// Copyright (C) 2026 Ryan C.
#define _GNU_SOURCE
#include "virtual_touchpad.h"
#include "gesture_control.h"
#include <errno.h>
#include <fcntl.h>
#include <glob.h>
#include <limits.h>
#include <pwd.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/stat.h>
#include <sys/sysmacros.h>
#include <time.h>
#include <unistd.h>

static volatile sig_atomic_t stopping;
struct gesture_session {
    struct gesture_control control;
    char path[PATH_MAX];
};
static int cancel_gestures(void *data)
{
    struct gesture_session *session=data;
    return gesture_request(&session->control, "CANCEL", session->path, 100);
}
static void handle_signal(int number) { (void)number; stopping = 1; }
static long long milliseconds(void)
{
    struct timespec now;
    if (clock_gettime(CLOCK_MONOTONIC, &now)) { perror("CLOCK_MONOTONIC"); exit(1); }
    return (long long)now.tv_sec * 1000 + now.tv_nsec / 1000000;
}
static int driver_matches(dev_t rdev)
{
    char link[PATH_MAX], target[PATH_MAX];
    snprintf(link, sizeof(link), "/sys/dev/char/%u:%u/device/device/driver", major(rdev), minor(rdev));
    if (!realpath(link, target)) return 0;
    const char *base = strrchr(target, '/');
    return base && !strcmp(base + 1, "t2_precision_trackpad");
}
static int validate(struct libevdev *dev, int fd)
{
    struct stat st;
    const char *phys = libevdev_get_phys(dev);
    if (fstat(fd, &st) || !S_ISCHR(st.st_mode) || !driver_matches(st.st_rdev) ||
        libevdev_get_id_vendor(dev) != 0x05ac || libevdev_get_id_product(dev) != 0x0340 ||
        libevdev_get_id_bustype(dev) != BUS_USB || !phys || !strstr(phys, "/input2") ||
        !libevdev_has_event_code(dev, EV_KEY, BTN_LEFT) ||
        !libevdev_has_property(dev, INPUT_PROP_POINTER) ||
        !libevdev_has_property(dev, INPUT_PROP_BUTTONPAD) ||
        libevdev_has_event_type(dev, EV_REL)) return -1;
    for (unsigned int key = 0; key < BTN_MISC; key++)
        if (libevdev_has_event_code(dev, EV_KEY, key)) return -1;
    const unsigned int required[] = {ABS_X, ABS_Y, ABS_MT_SLOT, ABS_MT_TRACKING_ID,
        ABS_MT_POSITION_X, ABS_MT_POSITION_Y, ABS_MT_TOUCH_MAJOR, ABS_MT_WIDTH_MAJOR};
    for (unsigned int i = 0; i < sizeof(required)/sizeof(required[0]); i++) {
        const struct input_absinfo *a = libevdev_get_abs_info(dev, required[i]);
        if (!a || a->maximum <= a->minimum) return -1;
    }
    const struct input_absinfo *slots = libevdev_get_abs_info(dev, ABS_MT_SLOT);
    if (slots->minimum != 0 || libevdev_get_num_slots(dev) < 1 ||
        libevdev_get_num_slots(dev) > MAX_SLOTS) return -1;
    for (unsigned int axis = ABS_MT_POSITION_X; axis <= ABS_MT_POSITION_Y; axis++)
        if (libevdev_get_abs_info(dev, axis)->resolution <= 0) return -1;
    return 0;
}
static int open_device(const char *path, struct libevdev **dev, int report_errors)
{
    int fd = open(path, O_RDONLY | O_NONBLOCK | O_CLOEXEC | O_NOCTTY);
    if (fd < 0) {
        if (report_errors) fprintf(stderr, "Opening %s: %s\n", path, strerror(errno));
        return -1;
    }
    int rc = libevdev_new_from_fd(fd, dev);
    if (rc < 0) {
        if (report_errors) fprintf(stderr, "Reading capabilities of %s: %s\n", path, strerror(-rc));
        libevdev_free(*dev); *dev = NULL; close(fd); return -1;
    }
    if (validate(*dev, fd)) {
        if (report_errors) fprintf(stderr, "Device identity/capability validation failed for %s\n", path);
        libevdev_free(*dev); *dev = NULL; close(fd); return -1;
    }
    return fd;
}
static int select_device(const char *override, char path[PATH_MAX], struct libevdev **dev)
{
    if (override) {
        if (!realpath(override, path)) return -1;
        return open_device(path, dev, 1);
    }
    glob_t nodes = {0};
    int selected = -1, matches = 0;
    if (glob("/dev/input/event*", 0, NULL, &nodes)) { globfree(&nodes); return -1; }
    for (size_t i = 0; i < nodes.gl_pathc; i++) {
        struct stat st;
        /* Inspect sysfs before opening anything: do not open keyboard nodes. */
        if (stat(nodes.gl_pathv[i], &st) || !driver_matches(st.st_rdev)) continue;
        struct libevdev *candidate = NULL;
        int fd = open_device(nodes.gl_pathv[i], &candidate, 0);
        if (fd < 0) continue;
        matches++;
        if (matches == 1) { selected = fd; *dev = candidate; snprintf(path, PATH_MAX, "%s", nodes.gl_pathv[i]); }
        else { libevdev_free(candidate); close(fd); }
    }
    globfree(&nodes);
    if (matches != 1) {
        if (selected >= 0) { libevdev_free(*dev); *dev = NULL; close(selected); }
        return -1;
    }
    return selected;
}
static void snapshot(struct libevdev *dev, struct frame *f)
{
    memset(f, 0, sizeof(*f));
    f->nslots = libevdev_get_num_slots(dev);
    f->button = libevdev_get_event_value(dev, EV_KEY, BTN_LEFT) != 0;
    for (int slot = 0; slot < f->nslots; slot++) {
        f->slots[slot].id = libevdev_get_slot_value(dev, slot, ABS_MT_TRACKING_ID);
        for (unsigned int axis = ABS_MT_TOUCH_MAJOR; axis <= ABS_MT_TOOL_Y; axis++)
            if (libevdev_has_event_code(dev, EV_ABS, axis))
                f->slots[slot].axes[axis] = libevdev_get_slot_value(dev, slot, axis);
    }
}
static int frame_valid(struct libevdev *dev, const struct frame *f)
{
    const struct input_absinfo *ids = libevdev_get_abs_info(dev, ABS_MT_TRACKING_ID);
    for (int i = 0; i < f->nslots; i++) {
        if (f->slots[i].id < -1 || f->slots[i].id > ids->maximum) return 0;
        if (f->slots[i].id < 0) continue;
        for (unsigned int a = ABS_MT_TOUCH_MAJOR; a <= ABS_MT_TOOL_Y; a++) {
            if (a == ABS_MT_TRACKING_ID) continue;
            const struct input_absinfo *info = libevdev_get_abs_info(dev, a);
            if (info && (f->slots[i].axes[a] < info->minimum ||
                         f->slots[i].axes[a] > info->maximum)) return 0;
        }
    }
    return 1;
}
static int idle(const struct frame *frame)
{
    if (frame->button) return 0;
    for (int i = 0; i < frame->nslots; i++) if (frame->slots[i].id >= 0) return 0;
    return 1;
}
static int sync_device(struct libevdev *dev, int force)
{
    struct input_event event;
    int rc;
    if (force && libevdev_next_event(dev, LIBEVDEV_READ_FLAG_FORCE_SYNC, &event) < 0) return -1;
    while ((rc = libevdev_next_event(dev, LIBEVDEV_READ_FLAG_SYNC, &event)) >= 0)
        if (stopping) return -1;
    return rc == -EAGAIN ? 0 : -1;
}
static int virtual_path(const char *sys_path, char path[PATH_MAX])
{
    char pattern[PATH_MAX + 8];
    glob_t nodes = {0};
    snprintf(pattern, sizeof(pattern), "%s/event*", sys_path);
    int rc = glob(pattern, 0, NULL, &nodes);
    if (rc || nodes.gl_pathc != 1) {
        errno=rc==GLOB_NOMATCH ? ENOENT : EINVAL;
        globfree(&nodes); return -1;
    }
    const char *name = strrchr(nodes.gl_pathv[0], '/');
    snprintf(path, PATH_MAX, "/dev/input/%s", name + 1);
    globfree(&nodes);
    /* Do not access the device node yet: DevicePolicy=closed denies even the
     * access() check until the launcher learns this path and grants access.
     * Sysfs discovery is enough to announce it; libinput verifies the actual
     * open and classification after the allowlist update. */
    return 0;
}
static int announce_file(const char *directory, const char *name, const char *path)
{
    if (!directory) return 0;
    char file[PATH_MAX];
    snprintf(file, sizeof(file), "%s/%s", directory, name);
    int fd = open(file, O_WRONLY | O_CREAT | O_EXCL | O_NOFOLLOW | O_CLOEXEC, 0600);
    if (fd < 0) return -1;
    size_t len = strlen(path);
    int rc = write(fd, path, len) == (ssize_t)len ? 0 : -1;
    close(fd);
    return rc;
}
static void usage(void)
{
    puts("Usage: palmreject MODE [--device PATH] [--config FILE] [--state-dir DIR] [--session-uid UID] [--duration SECONDS | --persistent]\n"
         "Modes: --probe | --observe | --passthrough | --filter\n"
         "Probe/observe never grab or create devices. Live modes require a supervised launcher.\n"
         "Filtering requires a calibrated profile. Trial duration: 1-86400 seconds, default 60.\n"
         "--persistent is for the installed filtering service only.\n"
         "palmreject --check-config FILE validates a profile without accessing devices.");
}
int main(int argc, char **argv)
{
    enum {NONE, PROBE, OBSERVE, PASSTHROUGH, FILTER} mode = NONE;
    const char *device = NULL, *config = NULL, *state_dir = NULL, *session_uid = NULL;
    const char *duration_arg=NULL;
    long duration=60;
    int persistent=0;
    uid_t session_user_id=0;
    gid_t session_group=0;
    if (argc == 3 && !strcmp(argv[1], "--check-config")) {
        struct profile checked;
        if (profile_read(argv[2], &checked)) { perror("Invalid profile"); return 2; }
        puts("Profile valid.");
        return 0;
    }
    for (int i = 1; i < argc; i++) {
        int next = NONE;
        if (!strcmp(argv[i], "--help")) { usage(); return 0; }
        if (!strcmp(argv[i], "--persistent")) {
            if (persistent) { usage(); return 2; }
            persistent=1; continue;
        }
        if (!strcmp(argv[i], "--probe")) next = PROBE;
        else if (!strcmp(argv[i], "--observe")) next = OBSERVE;
        else if (!strcmp(argv[i], "--passthrough")) next = PASSTHROUGH;
        else if (!strcmp(argv[i], "--filter")) next = FILTER;
        else if ((!strcmp(argv[i], "--device") || !strcmp(argv[i], "--config") ||
                  !strcmp(argv[i], "--state-dir") || !strcmp(argv[i], "--session-uid") ||
                  !strcmp(argv[i], "--duration")) && i + 1 < argc) {
            const char **dest = !strcmp(argv[i], "--device") ? &device :
                                !strcmp(argv[i], "--config") ? &config :
                                !strcmp(argv[i], "--session-uid") ? &session_uid :
                                !strcmp(argv[i], "--duration") ? &duration_arg : &state_dir;
            if (*dest) { usage(); return 2; }
            *dest = argv[++i]; continue;
        } else { usage(); return 2; }
        if (mode != NONE) { usage(); return 2; }
        mode = next;
    }
    if (mode == NONE || (mode == FILTER && !config) || (mode == PASSTHROUGH && config)) { usage(); return 2; }
    if (persistent && (mode != FILTER || duration_arg)) { usage(); return 2; }
    if (duration_arg) {
        if (mode < PASSTHROUGH || strlen(duration_arg) > 5 ||
            duration_arg[0] < '1' || duration_arg[0] > '9' ||
            strspn(duration_arg,"0123456789") != strlen(duration_arg)) { usage(); return 2; }
        duration=strtol(duration_arg,NULL,10);
        if (duration > 86400) { usage(); return 2; }
    }
    if (mode == FILTER) {
        char *end;
        if (!session_uid || !*session_uid || strspn(session_uid, "0123456789") != strlen(session_uid)) {
            fputs("Filtering requires --session-uid from a supervised launcher.\n", stderr); return 2;
        }
        errno=0;
        unsigned long uid=strtoul(session_uid, &end, 10);
        struct passwd *session_user;
        if (errno || *end || !uid || uid >= (uid_t)-1 || !(session_user=getpwuid((uid_t)uid))) {
            fputs("Invalid session UID.\n", stderr); return 2;
        }
        session_user_id=session_user->pw_uid;
        session_group=session_user->pw_gid;
    } else if (session_uid) { usage(); return 2; }
    struct profile profile;
    if (config && profile_read(config, &profile)) { perror("Invalid profile"); return 2; }
    if (mode >= PASSTHROUGH && !state_dir) {
        fputs("Use scripts/trial.sh or the installed service: live modes require supervision.\n", stderr); return 2;
    }
    char path[PATH_MAX];
    struct libevdev *dev = NULL;
    int fd = select_device(device, path, &dev);
    if (fd < 0) { fputs("No unique, accessible MacBookPro16,1 precision trackpad.\n", stderr); return 1; }
    setvbuf(stdout, NULL, _IOLBF, 0);
    printf("device=%s vendor=05ac product=0340 slots=%d name=%s\n", path,
           libevdev_get_num_slots(dev), libevdev_get_name(dev));
    unsigned char supported[ABS_CNT] = {0};
    for (unsigned int a = 0; a < ABS_CNT; a++) {
        const struct input_absinfo *info = libevdev_get_abs_info(dev, a);
        if (info) { supported[a] = 1; printf("axis=%u min=%d max=%d resolution=%d\n", a, info->minimum, info->maximum, info->resolution); }
    }
    int status = 0, vfd = -1, grabbed = 0, listener=-1;
    struct gesture_session gestures={.control={.fd=-1}};
    struct frame frame;
    struct filter filter;
    filter_init(&filter);
    if (mode == FILTER) {
        filter.cancel_gestures=cancel_gestures;
        filter.cancel_data=&gestures;
    }
    const struct input_absinfo *x = libevdev_get_abs_info(dev, ABS_MT_POSITION_X);
    if (mode == PROBE) goto done;
    struct sigaction action = {.sa_handler = handle_signal};
    sigemptyset(&action.sa_mask);
    if (sigaction(SIGINT, &action, NULL) || sigaction(SIGTERM, &action, NULL)) { status = 1; goto done; }
    long long deadline = milliseconds() + duration * 1000LL;
    if (sync_device(dev, 1)) { status = 1; goto done; }
    if (mode >= PASSTHROUGH) {
        char sys_path[PATH_MAX], vpath[PATH_MAX];
        vfd = virtual_touchpad_create(dev, sys_path, sizeof(sys_path));
        if (vfd < 0) { perror("Creating virtual touchpad"); status = 1; goto done; }
        printf("Virtual touchpad created: sysfs=%s\n",sys_path);
        long long ready_deadline = milliseconds() + 10000;
        int ready = 0, announced = 0, path_error=0;
        while (!stopping && milliseconds() < ready_deadline) {
            if (!virtual_path(sys_path, vpath)) {
                if (!announced) {
                    if (announce_file(state_dir, "virtual-device", vpath)) { status = 1; goto done; }
                    announced = 1;
                    printf("Virtual event node announced: %s; waiting for libinput recognition.\n",vpath);
                }
                if (virtual_touchpad_ready(vpath)) { ready = 1; break; }
            } else path_error=errno;
            usleep(100000);
        }
        if (!ready) {
            if (!announced)
                fprintf(stderr,"Virtual event node unavailable under %s: %s\n",sys_path,strerror(path_error));
            else
                fprintf(stderr,"Libinput did not recognize announced virtual node %s.\n",vpath);
            fputs("Virtual touchpad was not recognized; original input retained.\n", stderr);
            status = 1; goto done;
        }
        if (mode == FILTER) {
            snprintf(gestures.path, sizeof(gestures.path), "%s", vpath);
            listener=gesture_listen(state_dir, session_group);
            if (listener < 0 || gesture_accept(listener, session_user_id, &gestures.control, 10000) ||
                gesture_request(&gestures.control, "HELLO", vpath, 3000)) {
                fputs("KWin gesture cancellation unavailable; original input retained.\n", stderr);
                status=1; goto done;
            }
            close(listener); listener=-1;
        }
        /* Consume pending events, grab atomically, then force-sync. If a contact
         * arrived during handover, release immediately instead of forwarding it. */
        struct input_event event;
        int rc;
        while ((rc = libevdev_next_event(dev, LIBEVDEV_READ_FLAG_NORMAL, &event)) >= 0) {
            if (rc == LIBEVDEV_READ_STATUS_SYNC && sync_device(dev, 0)) { status = 1; goto done; }
            if (stopping || (!persistent && milliseconds() >= deadline)) goto done;
        }
        if (rc != -EAGAIN) { status = 1; goto done; }
        snapshot(dev, &frame);
        if (!idle(&frame)) { fputs("Lift all contacts and release buttons before retrying.\n", stderr); status = 1; goto done; }
        if (ioctl(fd, EVIOCGRAB, 1) < 0) { perror("Grabbing trackpad"); status = 1; goto done; }
        grabbed = 1;
        if (sync_device(dev, 1)) { status = 1; goto done; }
        snapshot(dev, &frame);
        if (!idle(&frame)) { status = 1; goto done; }
        if (filter_frame(&filter, &frame, NULL, x, supported, virtual_touchpad_write, &vfd)) { status = 1; goto done; }
        if (persistent) {
            if (announce_file(state_dir, "ready", "filtering")) { status=1; goto done; }
            puts("Persistent filtering active; supervised until stopped.");
        } else printf("Trial active; service and process have independent %ld-second limits.\n",duration);
    }
    int wait_idle = 0;
    unsigned char lifted[MAX_SLOTS]={0};
    int current_slot = libevdev_get_event_value(dev, EV_ABS, ABS_MT_SLOT);
    while (!stopping && (persistent || milliseconds() < deadline)) {
        if (mode == FILTER && !gesture_alive(&gestures.control)) {
            fputs("Gesture helper disconnected; releasing physical trackpad.\n", stderr);
            status=1; break;
        }
        struct input_event event;
        int rc = libevdev_next_event(dev, LIBEVDEV_READ_FLAG_NORMAL, &event);
        if (rc == -EAGAIN || rc == -EINTR) { usleep(5000); continue; }
        if (rc < 0) { fprintf(stderr, "Input error: %s\n", strerror(-rc)); status = 1; break; }
        if (rc == LIBEVDEV_READ_STATUS_SYNC) {
            if (mode == FILTER && cancel_gestures(&gestures)) { status=1; break; }
            if (vfd >= 0) {
                memset(&frame, 0, sizeof(frame)); frame.nslots = libevdev_get_num_slots(dev);
                for (int i = 0; i < frame.nslots; i++) frame.slots[i].id = -1;
                if (filter_frame(&filter, &frame, NULL, x, supported, virtual_touchpad_write, &vfd)) { status = 1; break; }
            }
            if (sync_device(dev, 0)) { status = 1; break; }
            wait_idle = 1;
            memset(lifted, 0, sizeof(lifted));
            current_slot = libevdev_get_event_value(dev, EV_ABS, ABS_MT_SLOT);
            continue;
        }
        if (event.type == EV_ABS && event.code == ABS_MT_SLOT) {
            current_slot = event.value;
            if (current_slot < 0 || current_slot >= libevdev_get_num_slots(dev)) { status = 1; break; }
        }
        /* Preserve liftoff even if the same tracking ID is reused in one frame. */
        if (event.type == EV_ABS && event.code == ABS_MT_TRACKING_ID && event.value == -1) {
            if (current_slot < 0 || current_slot >= libevdev_get_num_slots(dev)) { status=1; break; }
            lifted[current_slot]=1;
        }
        if (event.type != EV_SYN || event.code != SYN_REPORT) continue;
        snapshot(dev, &frame);
        memcpy(frame.lifted, lifted, sizeof(lifted));
        memset(lifted, 0, sizeof(lifted));
        if (!frame_valid(dev, &frame)) { status = 1; break; }
        if (mode == OBSERVE) {
            for (int i = 0; i < frame.nslots; i++) if (frame.slots[i].id >= 0)
                printf("slot=%d id=%d x=%d y=%d touch=%d width=%d palm=%d\n", i, frame.slots[i].id,
                    frame.slots[i].axes[ABS_MT_POSITION_X], frame.slots[i].axes[ABS_MT_POSITION_Y],
                    frame.slots[i].axes[ABS_MT_TOUCH_MAJOR], frame.slots[i].axes[ABS_MT_WIDTH_MAJOR],
                    config ? palm_candidate(&frame, &profile, x) : -1);
            continue;
        }
        if (wait_idle) { if (idle(&frame)) wait_idle = 0; continue; }
        if (filter_frame(&filter, &frame, mode == FILTER ? &profile : NULL, x,
                         supported, virtual_touchpad_write, &vfd)) {
            fputs("Virtual output failed; releasing physical trackpad.\n", stderr); status = 1; break;
        }
    }
done:
    /* Release physical input before any best-effort virtual cleanup. Closing the
     * descriptor also releases EVIOCGRAB after crashes and SIGKILL. */
    if (grabbed) ioctl(fd, EVIOCGRAB, 0);
    close(fd);
    if (listener >= 0) close(listener);
    if (vfd >= 0) {
        memset(&frame, 0, sizeof(frame)); frame.nslots = libevdev_get_num_slots(dev);
        for (int i = 0; i < frame.nslots; i++) frame.slots[i].id = -1;
        if (mode != FILTER || (gestures.control.fd >= 0 && !cancel_gestures(&gestures)))
            (void)filter_frame(&filter, &frame, NULL, x, supported, virtual_touchpad_write, &vfd);
        virtual_touchpad_destroy(vfd);
    }
    if (gestures.control.fd >= 0) close(gestures.control.fd);
    libevdev_free(dev);
    return status;
}
