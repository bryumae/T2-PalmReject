/* SPDX-License-Identifier: GPL-3.0-only */
#define _GNU_SOURCE
#include "gesture_control.h"
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <sys/un.h>
#include <sys/wait.h>
#include <time.h>
#include <unistd.h>

static void exchange(const char *reply, int delay_ms, int expected)
{
    int pair[2];
    assert(!socketpair(AF_UNIX,SOCK_SEQPACKET|SOCK_CLOEXEC,0,pair));
    pid_t pid=fork(); assert(pid>=0);
    if (!pid) {
        close(pair[0]);
        char request[256];
        ssize_t n=recv(pair[1],request,sizeof(request),0);
        const char *want="PR1 1 CANCEL /dev/input/event42";
        assert(n==(ssize_t)strlen(want) && !memcmp(request,want,(size_t)n));
        if (delay_ms) {
            struct timespec delay={.tv_nsec=delay_ms*1000000L};
            nanosleep(&delay,NULL);
        }
        if (reply) (void)send(pair[1],reply,strlen(reply),MSG_NOSIGNAL);
        close(pair[1]); _exit(0);
    }
    close(pair[1]);
    struct gesture_control control={.fd=pair[0]};
    assert(gesture_alive(&control));
    int result=gesture_request(&control,"CANCEL","/dev/input/event42",40);
    if (result != expected) fprintf(stderr,"exchange reply=%s delay=%d result=%d expected=%d\n",reply ? reply : "EOF",delay_ms,result,expected);
    assert(result==expected);
    close(pair[0]);
    int status; assert(waitpid(pid,&status,0)==pid);
    assert(WIFEXITED(status) && !WEXITSTATUS(status));
}
static void credentials(uid_t allowed, int expected)
{
    char directory[]="/tmp/palmreject-peer-XXXXXX";
    assert(mkdtemp(directory));
    struct sockaddr_un addr={.sun_family=AF_UNIX};
    snprintf(addr.sun_path,sizeof(addr.sun_path),"%s/socket",directory);
    int listener=socket(AF_UNIX,SOCK_SEQPACKET|SOCK_CLOEXEC,0);
    assert(listener>=0 && !bind(listener,(struct sockaddr *)&addr,sizeof(addr)) && !listen(listener,1));
    int client=socket(AF_UNIX,SOCK_SEQPACKET|SOCK_CLOEXEC,0);
    assert(client>=0 && !connect(client,(struct sockaddr *)&addr,sizeof(addr)));
    struct gesture_control control={.fd=-1};
    assert(gesture_accept(listener,allowed,&control,20)==expected);
    if (control.fd>=0) close(control.fd);
    close(client); close(listener); unlink(addr.sun_path); rmdir(directory);
}
int main(void)
{
    exchange("PR1 1 OK",0,0);
    exchange("PR1 2 OK",0,-1); /* Stale/out-of-order reply. */
    exchange("PR1 1 ERROR",0,-1);
    exchange("PR1 1 OK trailing",0,-1);
    exchange(NULL,0,-1); /* Helper exits during a request. */
    exchange("PR1 1 OK",100,-1); /* Bounded timeout. */
    credentials(getuid(),0);
    credentials(getuid()+1,-1);
    int pair[2]; assert(!socketpair(AF_UNIX,SOCK_SEQPACKET,0,pair));
    struct gesture_control control={.fd=pair[0]};
    assert(send(pair[1],"unexpected",10,0)==10);
    assert(!gesture_alive(&control));
    close(pair[1]);
    assert(gesture_request(&control,"CANCEL","/dev/input/event42",20)==-1);
    close(pair[0]);
    puts("gesture IPC/authentication/timeout tests passed");
}
