CC ?= cc
CPPFLAGS ?= -Iinclude $(shell pkg-config --cflags libevdev 2>/dev/null)
CFLAGS ?= -O2 -g -Wall -Wextra -Werror -std=c11
LDFLAGS ?=
LDLIBS ?= -l:libevdev.so.2 -linput
TARGET := palmreject
SOURCES := src/main.c src/filter.c src/virtual_touchpad.c src/gesture_control.c
HEADERS := include/virtual_touchpad.h include/evdev_api.h include/gesture_control.h

.PHONY: all clean test sanitize analyze
all: $(TARGET)
$(TARGET): $(SOURCES) $(HEADERS)
	$(CC) $(CPPFLAGS) $(CFLAGS) $(SOURCES) $(LDFLAGS) $(LDLIBS) -o $@
tests/test-filter: tests/test_filter.c src/filter.c $(HEADERS)
	$(CC) $(CPPFLAGS) $(CFLAGS) tests/test_filter.c src/filter.c $(LDFLAGS) -o $@
tests/test-input: tests/test_input.c $(SOURCES) $(HEADERS)
	$(CC) $(CPPFLAGS) $(CFLAGS) tests/test_input.c src/filter.c src/virtual_touchpad.c src/gesture_control.c $(LDFLAGS) $(LDLIBS) -Wl,--wrap=libevdev_next_event -o $@
tests/test-gesture: tests/test_gesture.c src/gesture_control.c $(HEADERS)
	$(CC) $(CPPFLAGS) $(CFLAGS) tests/test_gesture.c src/gesture_control.c $(LDFLAGS) -o $@
test: $(TARGET) tests/test-filter tests/test-input tests/test-gesture
	./tests/test-filter
	./tests/test-input
	./tests/test-gesture
	python3 tests/test_cli.py
	python3 tests/test_helper.py
sanitize:
	$(MAKE) clean
	$(MAKE) test CFLAGS='-O1 -g -Wall -Wextra -Werror -std=c11 -fsanitize=address,undefined -fno-omit-frame-pointer' LDFLAGS='-fsanitize=address,undefined'
analyze:
	$(CC) $(CPPFLAGS) $(CFLAGS) -fanalyzer $(SOURCES) $(LDLIBS) -o tests/palmreject-analyzed
clean:
	rm -f $(TARGET) tests/test-filter tests/test-input tests/test-gesture tests/palmreject-analyzed
