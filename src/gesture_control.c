/* SPDX-License-Identifier: GPL-3.0-only */
#define _GNU_SOURCE
#include "gesture_control.h"
#include <errno.h>
#include <fcntl.h>
#include <inttypes.h>
#include <poll.h>
#include <stdio.h>
#include <string.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <sys/un.h>
#include <time.h>
#include <unistd.h>

static long long now_ms(void)
{
    struct timespec t;
    if (clock_gettime(CLOCK_MONOTONIC, &t)) return -1;
    return (long long)t.tv_sec * 1000 + t.tv_nsec / 1000000;
}
static int wait_fd(int fd, short events, long long deadline)
{
    for (;;) {
        long long now = now_ms();
        if (now < 0 || now >= deadline) return -1;
        struct pollfd p = {.fd=fd, .events=events};
        int rc = poll(&p, 1, (int)(deadline-now));
        if (rc < 0 && errno == EINTR) continue;
        return rc > 0 && (p.revents & events) && !(p.revents & (POLLERR|POLLNVAL)) ? 0 : -1;
    }
}
int gesture_listen(const char *directory, gid_t group)
{
    struct sockaddr_un addr = {.sun_family=AF_UNIX};
    int n = snprintf(addr.sun_path, sizeof(addr.sun_path), "%s/control.sock", directory);
    if (n < 0 || (size_t)n >= sizeof(addr.sun_path)) { errno=ENAMETOOLONG; return -1; }
    int fd = socket(AF_UNIX, SOCK_SEQPACKET|SOCK_NONBLOCK|SOCK_CLOEXEC, 0);
    if (fd < 0) return -1;
    /* The launcher prepares this root-owned directory with the session group.
     * The service has no CAP_CHOWN, so the socket inherits that group (setgid). */
    /* Make the socket group-writable from creation, so a helper racing bind()
     * cannot encounter a transient EACCES before chmod(). */
    mode_t previous_mask=umask(0007);
    int bound=bind(fd, (struct sockaddr *)&addr, sizeof(addr));
    int saved_errno=errno;
    umask(previous_mask);
    errno=saved_errno;
    if (bound ||
        chmod(addr.sun_path, 0660) || listen(fd, 1)) goto fail;
    struct stat st;
    if (lstat(addr.sun_path, &st) || st.st_uid != 0 || st.st_gid != group ||
        !S_ISSOCK(st.st_mode)) goto fail;
    return fd;
fail:
    close(fd);
    return -1;
}
int gesture_accept(int listener, uid_t user, struct gesture_control *control, int timeout_ms)
{
    long long deadline = now_ms()+timeout_ms;
    while (!wait_fd(listener, POLLIN, deadline)) {
        int fd = accept4(listener, NULL, NULL, SOCK_NONBLOCK|SOCK_CLOEXEC);
        if (fd < 0) return -1;
        struct ucred peer;
        socklen_t size=sizeof(peer);
        if (!getsockopt(fd, SOL_SOCKET, SO_PEERCRED, &peer, &size) && peer.uid==user) {
            control->fd=fd; control->sequence=0; return 0;
        }
        close(fd);
    }
    return -1;
}
int gesture_request(struct gesture_control *control, const char *operation,
                    const char *device, int timeout_ms)
{
    char request[256], response[256], expected[256];
    if (control->fd < 0 || control->sequence == UINT64_MAX) return -1;
    uint64_t sequence=++control->sequence;
    int n=snprintf(request, sizeof(request), "PR1 %" PRIu64 " %s %s", sequence, operation, device);
    if (n < 0 || (size_t)n >= sizeof(request)) return -1;
    long long deadline=now_ms()+timeout_ms;
    if (wait_fd(control->fd, POLLOUT, deadline) ||
        send(control->fd, request, (size_t)n, MSG_NOSIGNAL) != n ||
        wait_fd(control->fd, POLLIN, deadline)) return -1;
    ssize_t got=recv(control->fd, response, sizeof(response), MSG_TRUNC);
    n=snprintf(expected, sizeof(expected), "PR1 %" PRIu64 " OK", sequence);
    return got==n && !memcmp(response, expected, (size_t)n) ? 0 : -1;
}
int gesture_alive(const struct gesture_control *control)
{
    char c;
    ssize_t n=recv(control->fd, &c, 1, MSG_PEEK|MSG_DONTWAIT);
    /* No unsolicited messages are valid. EOF and unexpected data both fail. */
    return n < 0 && (errno==EAGAIN || errno==EWOULDBLOCK);
}
